import os
import datetime
import tweepy
from flask import Flask, request, render_template, redirect, url_for, flash
from flask_apscheduler import APScheduler
from flask import session
from apscheduler.triggers.interval import IntervalTrigger
from oauth2client.service_account import ServiceAccountCredentials
import gspread
from pymongo import MongoClient
# Twitter API credentials
consumer_key = "ZCAFFYaMDNNAvzXFw8zibIO3F"
consumer_secret = "Rz5XpkU1shQ3X8xl8wXnBvKhyApvPgD7gyVL4XwS9dojas6c8q"
access_token = "1838845842150821892-Gbh5srs7lYCfJhJh9AAHLh90OSuK9S"
access_token_secret = "gWNqgVXGFhimxVELR1rtgAADj83aJWL4U21HHNwlcr3LK"
bearer_token = "AAAAAAAAAAAAAAAAAAAAAMZBwAEAAAAAydK4vUy1Z2pl9G%2BjaDmFiZJdXN4%3DZKUUQFoNBBCudtQAiGIU84gRnaZn3SLpyaRzfUgFA2n6X5rjf9"

app = Flask(__name__)
app.secret_key = '879237d417656cb16140f1dd4a4bbf5B'  # Replace with a secure secret key
# MongoDB setup
client = MongoClient("mongodb://localhost:27017/")  # Use your MongoDB URI here
db = client['tweet_scheduler']  # Database name
tweets_collection = db['scheduled_tweets']  # 
# Twitter API setup
auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
auth.set_access_token(access_token, access_token_secret)
api = tweepy.API(auth, wait_on_rate_limit=True)

client = tweepy.Client(bearer_token, consumer_key=consumer_key, consumer_secret=consumer_secret,
                       access_token=access_token, access_token_secret=access_token_secret, wait_on_rate_limit=True)

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name('tweet_schedule.json', scope)
gspread_client = gspread.authorize(creds)
sheet = gspread_client.open("Tweet Scheduler").sheet1


current_row_count = len(sheet.get_all_values())
new_row_count = current_row_count + 10
sheet.resize(rows=new_row_count)

# Scheduler setup
scheduler = APScheduler()
scheduled_tweets = []

@app.route('/schedule_page', methods=['GET', 'POST'])
def schedule_page():
    if 'username' not in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        tweet_text = request.form['tweet_text']
        scheduled_time = request.form.get('scheduled_time')
        image = request.files.get('image')
        image_path = None

        if image:
            image_path = os.path.join('uploads', image.filename)
            image.save(image_path)

        if scheduled_time:
            schedule_datetime = datetime.datetime.strptime(scheduled_time, "%Y-%m-%d %H:%M")
            row_index = add_tweet_to_sheet(tweet_text, image_path, schedule_datetime, "pending")
            scheduled_tweets.append({
                'text': tweet_text,
                'image': image_path,
                'time': schedule_datetime,
                'row_index': row_index
            })
            flash('Tweet scheduled successfully!', 'success')
        else:
            try:
                if image_path:
                    media_id = api.media_upload(image_path).media_id_string
                    client_tweepy.create_tweet(text=tweet_text, media_ids=[media_id])
                else:
                    client_tweepy.create_tweet(text=tweet_text)

                add_tweet_to_sheet(tweet_text, image_path, datetime.datetime.now(), "done")
                flash('Tweet posted successfully!', 'success')
            except Exception as e:
                flash(f"An error occurred: {e}", 'error')

        return redirect(url_for('schedule_page'))

    return render_template('scheduler.html', scheduled_tweets=scheduled_tweets)
# Function to post scheduled tweets
@app.route('/post_scheduled_tweets')
def post_scheduled_tweets():
    global scheduled_tweets
    now = datetime.datetime.now()
    tweets_to_post = [tweet for tweet in scheduled_tweets if tweet['time'] <= now]
    for tweet in tweets_to_post:
        try:
            if tweet['image']:
                media_id = api.media_upload(tweet['image']).media_id_string
                client.create_tweet(text=tweet['text'], media_ids=[media_id])
            else:
                client.create_tweet(text=tweet['text'])
            update_tweet_status(tweet['row_index'], "done")  # Update status to "done"
            scheduled_tweets.remove(tweet)
            print(f"Scheduled tweet posted: {tweet['text']}")
        except Exception as e:
            print(f"An error occurred while posting tweet: {e}")


# Route for login page
@app.route('/')
def index():
    if 'username' not in session:
        return render_template('login.html')
    return redirect(url_for('schedule_page'))

# Route for Twitter login
@app.route('/login', methods=['POST'])
def login():
    try:
        auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
        redirect_url = auth.get_authorization_url()
        session['request_token'] = auth.request_token
        return redirect(redirect_url)
    except tweepy.TweepyException as e:
        flash(f'Failed to get request token: {e}')
        return redirect(url_for('index'))

# Callback route after Twitter authentication
@app.route('/callback')
def callback():
    request_token = session.pop('request_token', None)
    auth.request_token = request_token
    try:
        auth.get_access_token(request.args.get('oauth_verifier'))
        api = tweepy.API(auth)
        user = api.verify_credentials()
        session['username'] = user.screen_name
        return redirect(url_for('schedule_page'))
    except tweepy.TweepyException as e:
        flash(f'Error during authentication: {e}')
        return redirect(url_for('index'))

# Find row by tweet text in Google Sheets
def find_row_by_tweet_text(tweet_text):
    try:
        cell = sheet.find(tweet_text)
        return cell.row if cell else None
    except Exception as e:
        print(f"Error finding row: {e}")
        return None


@app.route('/delete_tweet/<int:index>', methods=['POST'])
def delete_tweet(index):
    if index < len(scheduled_tweets):
        tweet_to_delete = scheduled_tweets[index]
        scheduled_tweets.remove(tweet_to_delete)
        
        # Ensure correct row index is used for Google Sheets update
        row_index = tweet_to_delete.get('row_index')
        if row_index:
            update_tweet_status(row_index, "deleted")
            flash('Tweet deleted successfully!', 'success')
        else:
            flash('Tweet not found in Google Sheets.', 'error')
    else:
        flash('Tweet not found in application.', 'error')
    return redirect(url_for('schedule_page'))

@app.route('/edit_tweet/<int:index>', methods=['GET', 'POST'])
def edit_tweet(index):
    if index < len(scheduled_tweets):
        tweet = scheduled_tweets[index]

        if request.method == 'POST':
            new_text = request.form.get('tweet_text')
            new_image = request.files.get('image')
            if not new_text:
                flash("Tweet text cannot be empty.", "error")
                return redirect(url_for('edit_tweet', index=index))
            
            # Update tweet text and image path in local scheduled_tweets list
            tweet['text'] = new_text
            image_path = tweet['image']
            
            if new_image:
                image_path = os.path.join('uploads', new_image.filename)
                new_image.save(image_path)
                tweet['image'] = image_path

            # Update tweet details in Google Sheets
            row_index = tweet['row_index']
            if row_index:
                try:
                    sheet.update_cell(row_index, 1, new_text)  # Update text
                    sheet.update_cell(row_index, 2, image_path)  # Update image path
                    
                    # Update MongoDB document
                    update_data = {
                        "tweet_content": new_text,
                        "image_path": image_path,
                        "scheduled_time": tweet['time']
                    }
                    
                    # Find and update the document in MongoDB
                    result = tweets_collection.update_one(
                        {"scheduled_time": tweet['time']},  # Use scheduled_time as identifier
                        {"$set": update_data}
                    )
                    
                    if result.modified_count > 0:
                        flash('Tweet updated successfully in all databases!', 'success')
                    else:
                        flash('Tweet updated in sheets but not found in MongoDB.', 'warning')
                        
                except Exception as e:
                    flash(f"Failed to update tweet: {e}", 'error')
            
            return redirect(url_for('schedule_page'))

        return render_template('edit_tweet.html', tweet=tweet, index=index)
# Helper function to add tweet to Google Sheets
def add_tweet_to_sheet(tweet_content, image_path, scheduled_time, status):
    # Add tweet to Google Sheets
    row = [tweet_content, image_path, scheduled_time.strftime("%Y-%m-%d %H:%M:%S"), status]
    sheet.append_row(row)   
    # Add tweet to MongoDB
    tweet_data = {
        "tweet_content": tweet_content,
        "image_path": image_path,
        "scheduled_time": scheduled_time,
        "status": status
    }
    tweets_collection.insert_one(tweet_data)  # Store in MongoDB
    return sheet.row_count  

# Helper function to update tweet status in Google Sheets
def update_tweet_status(row_index, status):
    try:
        # Update status in Google Sheets
        if row_index and row_index <= sheet.row_count:
            sheet.update_cell(row_index, 4, status)        
        # Update status in MongoDB
        tweet_data = tweets_collection.find_one({"_id": row_index})  # Find tweet by row_index
        if tweet_data:
            tweets_collection.update_one({"_id": row_index}, {"$set": {"status": status}})
    except Exception as e:
        print(f"Failed to update status: {e}")

@app.route('/upload_file', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        text = request.form['tweet_text']
        image = request.files.get('image')
        action = request.form['action']       
        image_path = None
        if image:
            image_path = os.path.join('uploads', image.filename)
            image.save(image_path)
        if action == "post_now":
            try:
                if image_path:
                    media_id = api.media_upload(image_path).media_id_string
                    client.create_tweet(text=text, media_ids=[media_id])
                else:
                    client.create_tweet(text=text)
                add_tweet_to_sheet(text, image_path, datetime.datetime.now(), "done")
                flash('Tweet posted successfully!', 'success')
            except Exception as e:
                flash(f"An error occurred: {e}", 'error')
        elif action == "schedule":
            schedule_date = request.form.get('tweet_date')
            schedule_time = request.form.get('tweet_time')
            if schedule_date and schedule_time:
                try:
                    schedule_datetime = datetime.datetime.strptime(f"{schedule_date} {schedule_time}", "%Y-%m-%d %H:%M")
                    row_index = add_tweet_to_sheet(text, image_path, schedule_datetime, "pending")
                    scheduled_tweets.append({
                        'text': text,
                        'image': image_path,
                        'time': schedule_datetime,
                        'status': "pending",
                        'row_index': row_index
                    })
                    flash('Tweet scheduled successfully!', 'success')
                except ValueError as e:
                    flash(f"Error scheduling tweet: {e}", 'error')
        return redirect(url_for('upload_file'))
    return render_template('scheduler.html', scheduled_tweets=scheduled_tweets)

# Add tweet to Google Sheets


# Start the scheduler
scheduler.add_job(func=post_scheduled_tweets, trigger=IntervalTrigger(seconds=60), id='post_scheduled_tweets', replace_existing=True)
scheduler.start()

if __name__ == '__main__':
    os.makedirs('uploads', exist_ok=True)
    app.run(debug=True, port=5003)