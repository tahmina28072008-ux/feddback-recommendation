# main.py

from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
import logging
import os
import datetime
from twilio.rest import Client

# ------------------------------------------------------
# Logging Configuration
# ------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ------------------------------------------------------
# Flask Initialization
# ------------------------------------------------------
app = Flask(__name__)

# ------------------------------------------------------
# Twilio Setup
# ------------------------------------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")  # Replace with your Account SID
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")  # Replace with your Auth Token
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")  # Replace with your Twilio phone number

twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    try:
        twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        logging.info("✅ Twilio client initialized successfully.")
    except Exception as e:
        logging.error(f"❌ Error initializing Twilio client: {e}")
else:
    logging.warning("⚠️ Twilio credentials not found. WhatsApp messages will not be sent.")

def format_phone_number(number: str) -> str:
    """
    Formats a phone number to E.164 format.
    - If UK local (07...), convert to +44
    - If no '+' prefix, add it
    """
    number = number.strip()
    if number.startswith("07") and len(number) == 11:
        return f"+44{number[1:]}"
    if not number.startswith("+"):
        return f"+{number}"
    return number

def send_whatsapp_message(to_number: str, message_body: str):
    """Send a WhatsApp message using Twilio API."""
    if not twilio_client:
        return False, "Twilio client not initialized."

    try:
        formatted_to = f"whatsapp:{format_phone_number(to_number)}"
        logging.info(f"📤 Sending WhatsApp message to {formatted_to}")
        twilio_client.messages.create(
            to=formatted_to,
            from_=f"whatsapp:{TWILIO_PHONE_NUMBER}",
            body=message_body
        )
        logging.info("✅ WhatsApp message sent successfully.")
        return True, "Message sent successfully."
    except Exception as e:
        logging.error(f"❌ Failed to send WhatsApp message: {e}")
        return False, f"Failed to send message: {e}"

# ------------------------------------------------------
# Firestore Setup
# ------------------------------------------------------
db = None
try:
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    logging.info("✅ Firestore connected using Cloud Run environment credentials.")
except ValueError:
    try:
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            cred = credentials.Certificate(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            logging.info("✅ Firestore connected using GOOGLE_APPLICATION_CREDENTIALS.")
        else:
            logging.warning("⚠️ No GOOGLE_APPLICATION_CREDENTIALS found. Running without Firestore.")
    except Exception as e:
        logging.error(f"❌ Error initializing Firebase: {e}")
        logging.warning("Continuing without database connection.")

# ------------------------------------------------------
# Webhook Endpoint
# ------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json(silent=True, force=True)

    # Default fallback response
    fulfillment_response = {
        "fulfillmentResponse": {
            "messages": [
                {"text": {"text": ["I'm sorry, I didn't understand that. Could you please rephrase?"]}}
            ]
        }
    }

    try:
        intent_display_name = req.get("intentInfo", {}).get("displayName")
        tag = req.get("fulfillmentInfo", {}).get("tag")
        parameters = req.get("sessionInfo", {}).get("parameters", {})

        logging.info(f"🎯 Intent: {intent_display_name}, Tag: {tag}, Parameters: {parameters}")

        # --- Handle Feedback ---
        if intent_display_name == "FeedbackIntent" or tag == "feedback-recommend":
            feedback_text = parameters.get("feedback_text")
            if feedback_text and db is not None:
                try:
                    doc_ref = db.collection("feedback").add({
                        "text": feedback_text,
                        "timestamp": datetime.datetime.utcnow()
                    })
                    logging.info(f"💾 Feedback saved with ID: {doc_ref[1].id}")
                    message = "Thank you for your feedback! It has been recorded."
                except Exception as e:
                    logging.error(f"❌ Error saving feedback to Firestore: {e}")
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
                success, response_message = send_whatsapp_message(recipient_number, message_body)
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
        logging.error(f"❌ Webhook error: {e}")
        fulfillment_response = {
            "fulfillmentResponse": {
                "messages": [{"text": {"text": [f"Unexpected error: {e}"]}}]
            }
        }

    return jsonify(fulfillment_response)

# ------------------------------------------------------
# App Runner
# ------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
