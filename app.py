# app.py
from flask import Flask
from flask_cors import CORS
from models import db
from routes.email import email_bp
from routes.tracking import track_bp
from dotenv import load_dotenv
from scheduler import start_scheduler
from utils.logger import logger
import os

load_dotenv()
app = Flask(__name__)
CORS(app)

# Define root route
@app.route('/')
def home():
    logger.info("Home endpoint accessed")
    return "Welcome to the mailer system!"

# Configure database connection
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Register database and blueprint routes
db.init_app(app)
app.register_blueprint(email_bp)
app.register_blueprint(track_bp)

if __name__ == '__main__':
    logger.info("Starting mailer application")
    
    # Initialize database tables
    with app.app_context():
        logger.info("Creating database tables if they don't exist")
        db.create_all()
        
        # Start scheduled tasks
        logger.info("Starting scheduler")
        start_scheduler(app)
    
    logger.info("Running Flask application")
    app.run(debug=True)
    # Production configuration
    # app.run(host='0.0.0.0', port=10000)