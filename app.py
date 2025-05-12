# app.py
from flask import Flask
from flask_cors import CORS
from models import db
from routes.email import email_bp
from dotenv import load_dotenv
import os
from routes.tracking import track_bp

load_dotenv()

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return "Welcome to the mailer system!"

# Connect to MySQL
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Register DB and Routes
db.init_app(app)
app.register_blueprint(email_bp)
app.register_blueprint(track_bp)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Creates tables from models.py
    # app.run(debug=True)
    app.run(host='0.0.0.0', port=10000)
