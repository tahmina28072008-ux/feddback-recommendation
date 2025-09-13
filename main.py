# main.py  --- End Conversation Flow Webhook

from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
import logging
import os
import datetime
from twilio.rest import Client

# ---------------- Logging ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ---------------- Flask App ----------------
app = Flask(__name__)

# ---------------- Twilio Setup ----------------
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

# ---------------- Firestore Setup ----------------
db = None
try:
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    logging.info("Firestore connected using Cloud Run environment credentials.")
except ValueError:
    try:
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            cred = credentials.Certificate(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            logging.info("Firestore connected using GOOGLE_APPLICATION_CREDENTIALS.")
        else:
            logging.warning("No GOOGLE_APPLICATION_CREDENTIALS found. Running without Firestore.")
    except Exception as e:
        logging.error(f"Error initializing Firebase: {e}")
        logging.warning("Continuing without database connection.")

# ---------------- Helper Functions ----------------
def send_whatsapp_message(to_number, message_body):
    """Send a WhatsApp message via Twilio"""
    from_number = "whatsapp:+14155238886"  # Twilio Sandbox number
    if not twilio_client:
        return False, "Twilio client is not initialized. Cannot send message."

    try:
        logging.info(f"Sending WhatsApp message to {to_number}")
        twilio_client.messages.create(
            to=to_number,
            from_=from_number,
            body=message_body
        )
        return True, "Message sent successfully."
    except Exception as e:
        logging.error(f"Twilio send error: {e}")
        return False, f"Failed to send message: {e}"

def format_phone_number(number):
    """Format UK mobile number into E.164 (+44)"""
    cleaned_number = ''.join(filter(str.isdigit, number))
    if cleaned_number.startswith("07") and len(cleaned_number) == 11:
        return f"+44{cleaned_number[1:]}"
    return cleaned_number

# ---------------- Webhook ----------------
@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json(silent=True, force=True)
    logging.info(f"Webhook request: {req}")

    fulfillment_response = {
        "fulfillmentResponse": {
            "messages": [
                {"text": {"text": ["I'm sorry, I didn’t understand that. Could you rephrase?"]}}
            ]
        }
    }

    try:
        intent_display_name = req.get("intentInfo", {}).get("displayName")
        parameters = req.get("sessionInfo", {}).get("parameters", {})

        logging.info(f"Intent received: {intent_display_name}")
        logging.info(f"Parameters: {parameters}")

        # ---------- Feedback Intent ----------
        if intent_display_name == "FeedbackIntent":
            feedback_text = parameters.get("feedback_text")

            if feedback_text and db is not None:
                try:
                    doc_ref = db.collection("feedback").add({
                        "text": feedback_text,
                        "timestamp": datetime.datetime.utcnow()
                    })
                    logging.info(f"Feedback saved with ID: {doc_ref[1].id}")
                    message = "✅ Thank you for your feedback! It has been recorded."
                except Exception as e:
                    logging.error(f"Firestore error: {e}")
                    message = "⚠️ Sorry, we couldn’t save your feedback. Please try again later."
            else:
                message = "⚠️ Feedback not saved (missing text or DB unavailable)."

            fulfillment_response = {
                "fulfillmentResponse": {
                    "messages": [{"text": {"text": [message]}}]
                }
            }

        # ---------- Recommend Intent ----------
        elif intent_display_name == "RecommendIntent":
            recipient_number = parameters.get("recipient_phone_number")
            share_link = "https://example.com/share"
            message_body = f"👋 Hello! I wanted to recommend this service to you. Check it out here: {share_link}"

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
                        "messages": [{"text": {"text": ["⚠️ No valid phone number received. Please try again."]}}]
                    }
                }

    except Exception as e:
        logging.error(f"Webhook error: {e}")
        fulfillment_response = {
            "fulfillmentResponse": {
                "messages": [
                    {"text": {"text": [f"❌ Unexpected error: {str(e)}. Please try again later."]}}
                ]
            }
        }

    return jsonify(fulfillment_response)

# ---------------- Main ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
