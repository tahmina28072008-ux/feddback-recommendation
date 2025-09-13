# end_conversation_webhook.py

from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
import logging
import os
import datetime
from twilio.rest import Client

# Configure logging to provide more details in the console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize Flask app
app = Flask(__name__)

# --- Twilio Configuration ---
# Twilio credentials should be set as environment variables.
account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
twilio_client = Client(account_sid, auth_token)

# --- Firestore Connection Setup ---
# Attempt to initialize Firebase with different credential methods.
db = None
try:
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred)
    logging.info("Firestore connected using Cloud Run environment credentials.")
    db = firestore.client()
except ValueError:
    try:
        if os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
            cred = credentials.Certificate(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'))
            firebase_admin.initialize_app(cred)
            logging.info("Firestore connected using GOOGLE_APPLICATION_CREDENTIALS.")
            db = firestore.client()
        else:
            logging.warning("No GOOGLE_APPLICATION_CREDENTIALS found. Running in mock data mode.")
    except Exception as e:
        logging.error(f"Error initializing Firebase: {e}")
        logging.warning("Continuing without database connection. Using mock data.")

def send_whatsapp_message(to_number, message_body):
    """
    Sends a WhatsApp message using the Twilio client.
    
    Args:
        to_number (str): The recipient's phone number in E.164 format.
        message_body (str): The body of the message to send.

    Returns:
        tuple: A boolean indicating success and a string message.
    """
    from_number = "whatsapp:+14155238886"  # Your Twilio Sandbox number
    try:
        logging.info(f"Attempting to send WhatsApp message to {to_number}")
        twilio_client.messages.create(
            to=to_number,
            from_=from_number,
            body=message_body
        )
        logging.info("WhatsApp message sent successfully.")
        return True, "Message sent successfully."
    except Exception as e:
        logging.error(f"Failed to send WhatsApp message: {e}")
        return False, f"Failed to send message: {e}"

def format_phone_number(number):
    """
    Formats a UK phone number to E.164 format.
    Assumes a UK number starts with 07 and is 11 digits long.
    You may need to adapt this function for other country codes.
    """
    cleaned_number = ''.join(filter(str.isdigit, number))
    if cleaned_number.startswith('07') and len(cleaned_number) == 11:
        return f"+44{cleaned_number[1:]}"
    return cleaned_number

@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Handles a POST request from a Dialogflow CX agent, specifically for the
    end conversation flow.
    """
    req = request.get_json(silent=True, force=True)

    # Default fallback response for Dialogflow
    fulfillment_response = {
        "fulfillmentResponse": {
            "messages": [
                {"text": {"text": ["I'm sorry, I didn't understand that. Could you please rephrase?"]}}
            ]
        }
    }

    try:
        # Extract intent name and session parameters
        intent_display_name = req.get("intentInfo", {}).get("displayName")
        parameters = req.get("sessionInfo", {}).get("parameters", {})
        
        logging.info(f"Received webhook request for intent: {intent_display_name}")

        # --- Handle Feedback Intent ---
        if intent_display_name == 'FeedbackIntent':
            # This intent is triggered after the user provides their feedback text.
            feedback_text = parameters.get('feedback_text') # Assuming a parameter named 'feedback_text' is configured.
            
            if feedback_text and db is not None:
                try:
                    # Save the feedback to the 'feedback' collection in Firestore
                    doc_ref = db.collection('feedback').add({
                        'text': feedback_text,
                        'timestamp': datetime.datetime.now()
                    })
                    logging.info(f"Feedback successfully saved with ID: {doc_ref[1].id}")
                    message = "Thank you for your feedback! It has been recorded."
                except Exception as e:
                    logging.error(f"Error saving feedback to Firestore: {e}")
                    message = "Sorry, I couldn't save your feedback at this time. Please try again later."
            else:
                message = "Sorry, I couldn't save your feedback because the database is not connected or no text was provided."
            
            fulfillment_response = {
                "fulfillmentResponse": {
                    "messages": [
                        {"text": {"text": [message]}}
                    ]
                }
            }

        # --- Handle SendRecommendation Intent ---
        elif intent_display_name == 'RecommendIntent':
            # This intent is triggered after the user provides the recipient's phone number.
            recipient_number = parameters.get('recipient_phone_number')
            
            # This is the link you want to share via WhatsApp.
            share_link = "https://www.google.com/search?q=https://example.com/share"
            message_body = f"Hello! I wanted to recommend this service to you. Check it out here: {share_link}"
            
            if recipient_number:
                # Format the number to the E.164 format required by Twilio
                formatted_number = format_phone_number(recipient_number)
                
                # Call the Twilio helper function
                success, response_message = send_whatsapp_message(formatted_number, message_body)
                
                fulfillment_response = {
                    "fulfillmentResponse": {
                        "messages": [
                            {"text": {"text": [response_message]}}
                        ]
                    }
                }
            else:
                # Handle the case where the phone number parameter is missing
                fulfillment_response = {
                    "fulfillmentResponse": {
                        "messages": [
                            {"text": {"text": ["Sorry, I did not receive a valid phone number. Please try again."]}}
                        ]
                    }
                }

    except Exception as e:
        logging.error(f"Webhook error: {e}")
        # Return a generic error message to Dialogflow
        fulfillment_response = {
            "fulfillmentResponse": {
                "messages": [
                    {"text": {"text": [f"An unexpected error occurred: {e}. Please try again later."]}}
                ]
            }
        }

    return jsonify(fulfillment_response)

if __name__ == '__main__':
    # This is for local development. For production, the port is set by the environment.
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
