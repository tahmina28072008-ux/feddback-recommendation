# main.py

from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
import logging
import os
import datetime
from twilio.rest import Client

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Initialize Flask
app = Flask(__name__)

# --- Twilio Setup ---
account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
auth_token = os.environ.get("TWILIO_AUTH_TOKEN")

twilio_client = None
if account_sid and auth_token:
    try:
        twilio_client = Client(account_sid, auth_token)
        logging.info("Twilio client initialized successfully.")
    except Exception as e:
        logging.error(f"Error initializing Twilio client: {e}")
else:
    logging.warning("Twilio credentials not found. WhatsApp messages will not be sent.")

# --- Firestore Setup ---
db = None
try:
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred)
    logging.info("Firestore connected using Cloud Run environment credentials.")
    db = firestore.client()
except ValueError:
    try:
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            cred = credentials.Certificate(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
            firebase_admin.initialize_app(cred)
            logging.info("Firestore connected using GOOGLE_APPLICATION_CREDENTIALS.")
            db = firestore.client()
        else:
            logging.warning("No GOOGLE_APPLICATION_CREDENTIALS found. Running without Firestore.")
    except Exception as e:
        logging.error(f"Error initializing Firebase: {e}")
        logging.warning("Continuing without database connection.")

# --- Helper: WhatsApp messaging ---
def send_whatsapp_message(to_number, message_body):
    from_number = "whatsapp:+14155238886"  # Twilio Sandbox Number
    if not twilio_client:
        return False, "Twilio client not initialized."

    try:
        logging.info(f"Sending WhatsApp message to {to_number}")
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

# --- Helper: Format phone numbers ---
def format_phone_number(number):
    cleaned_number = "".join(filter(str.isdigit, number))
    if cleaned_number.startswith("07") and len(cleaned_number) == 11:
        return f"+44{cleaned_number[1:]}"  # UK E.164 format
    if not cleaned_number.startswith("+"):
        return f"+{cleaned_number}"
    return cleaned_number

# --- Webhook ---
@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json(silent=True, force=True)

    fulfillment_response = {
        "fulfillmentResponse": {
            "messages": [
                {"text": {"text": ["I'm sorry, I didn't understand that. Could you please rephrase?"]}}
            ]
        }
    }

    try:
        # Extract intent and tag
        intent_display_name = req.get("intentInfo", {}).get("displayName")
        tag = req.get("fulfillmentInfo", {}).get("tag")
        parameters = req.get("sessionInfo", {}).get("parameters", {})

        logging.info(f"Intent received: {intent_display_name}")
        logging.info(f"Tag received: {tag}")
        logging.info(f"Parameters: {parameters}")

        # --- Handle Feedback ---
        if intent_display_name == "FeedbackIntent" or tag == "feedback-recommend":
            feedback_text = parameters.get("feedback_text")
            if feedback_text and db is not None:
                try:
                    doc_ref = db.collection("feedback").add({
                        "text": feedback_text,
                        "timestamp": datetime.datetime.now()
                    })
                    logging.info(f"Feedback saved with ID: {doc_ref[1].id}")
                    message = "Thank you for your feedback! It has been recorded."
                except Exception as e:
                    logging.error(f"Error saving feedback to Firestore: {e}")
                    message = "Sorry, I couldn't save your feedback at this time."
            else:
                message = "Sorry, no feedback text provided or database unavailable."

            fulfillment_response = {
                "fulfillmentResponse": {
                    "messages": [{"text": {"text": [message]}}]
                }
            }

        # --- Handle Recommend ---
        elif intent_display_name == "RecommendIntent" or tag == "recommend-share":
            recipient_number = parameters.get("recipient_phone_number")
            share_link = "https://example.com/share"
            message_body = f"Hello! I wanted to recommend this service to you. Check it out here: {share_link}"

            if recipient_number:
                formatted_number = format_phone_number(recipient_number)
                success, response_message = send_whatsapp_message(formatted_number, message_body)
                fulfillment_response = {
                    "fulfillmentResponse": {
                        "messages": [{"text": {"text": [response_message]}}]
                    }
                }
            else:
                fulfillment_response = {
                    "fulfillmentResponse": {
                        "messages": [{"text": {"text": ["Sorry, I did not receive a valid phone number."]}}]
                    }
                }

    except Exception as e:
        logging.error(f"Webhook error: {e}")
        fulfillment_response = {
            "fulfillmentResponse": {
                "messages": [{"text": {"text": [f"Unexpected error: {e}"]}}]
            }
        }

    return jsonify(fulfillment_response)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
