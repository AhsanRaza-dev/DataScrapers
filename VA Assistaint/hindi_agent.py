import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client
from huggingface_hub import InferenceClient
import uuid

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
HF_TOKEN = os.getenv('HF_TOKEN')
NGROK_URL = os.getenv('NGROK_URL')

# Validate environment variables
if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, HF_TOKEN, NGROK_URL]):
    logger.error("Missing required environment variables")
    raise ValueError("Please set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, HF_TOKEN, and NGROK_URL in .env")

# Initialize clients
try:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
except Exception as e:
    logger.error(f"Twilio client error: {e}")
    exit(1)

try:
    hf_client = InferenceClient(
        provider="novita",
        api_key=HF_TOKEN,
    )
    
    test_response = hf_client.chat.completions.create(
        model="meta-llama/Llama-3.2-3B-Instruct",
        messages=[{"role": "user", "content": "नमस्ते"}],
        max_tokens=10,
        temperature=0.7
    )
except Exception as e:
    logger.warning(f"Hugging Face client error: {e}")
    hf_client = None

# Store conversations
conversations = {}

class AIPhoneAgent:
    def __init__(self):
        self.system_prompt = """आप एक मददगार AI फोन असिस्टेंट हैं। 
        जवाब सरल, स्पष्ट और 20 शब्दों से कम रखें। दोस्ताना अंदाज में हिंदी में बात करें। 
        एक स्पष्ट प्रश्न पूछें। फोन कॉल के लिए आसान शब्दों का उपयोग करें। 
        हमेशा फॉलो-अप प्रश्न के साथ समाप्त करें।"""
    
    def generate_response(self, user_input, call_sid):
        """Generate AI response with better error handling"""
        try:
            if not hf_client:
                return self.get_fallback_response(user_input)
            
            if call_sid not in conversations:
                conversations[call_sid] = []
            
            conversations[call_sid].append({"role": "user", "content": user_input})
            
            messages = [{"role": "system", "content": self.system_prompt}]
            recent_messages = conversations[call_sid][-6:]
            messages.extend(recent_messages)
            
            response = hf_client.chat.completions.create(
                model="meta-llama/Llama-3.2-3B-Instruct",
                messages=messages,
                max_tokens=50,
                temperature=0.7,
                top_p=0.9,
                frequency_penalty=0.1
            )
            
            ai_response = response.choices[0].message.content.strip()
            
            if not ai_response or len(ai_response) < 3:
                return self.get_fallback_response(user_input)
            
            ai_response = self.clean_response(ai_response)
            conversations[call_sid].append({"role": "assistant", "content": ai_response})
            
            return ai_response
            
        except Exception as e:
            logger.error(f"Error generating response: {str(e)}")
            return self.get_fallback_response(user_input, error=True)
    
    def get_fallback_response(self, user_input, error=False):
        """Enhanced fallback responses in Hindi"""
        if error:
            return "क्षमा करें, मुझे समस्या हो रही है। फिर से बोलें?"
        
        user_lower = user_input.lower()
        fallback_responses = {
            "नमस्ते": "नमस्ते! आपसे मिलकर खुशी हुई। क्या बात करना चाहते हैं?",
            "हाय": "हाय! आप कैसे हैं? क्या मदद चाहिए?",
            "हेलो": "हेलो! आपसे मिलकर अच्छा लगा। क्या बताएंगे?",
            "मदद": "मैं मदद के लिए हूँ! क्या चाहिए?",
            "मौसम": "मौसम नहीं देख सकता। आपका दिन कैसा है?",
            "समय": "समय नहीं बता सकता। क्या बात करना चाहते हैं?",
            "अलविदा": "बात करके अच्छा लगा! शानदार दिन बिताएं!",
            "धन्यवाद": "धन्यवाद! और क्या मदद करूँ?",
            "आप कैसे हैं": "मैं ठीक हूँ! आप कैसे हैं?",
        }
        
        for key, response in fallback_responses.items():
            if key in user_lower:
                return response
        
        return f"आपने '{user_input}' कहा। और बताएं?"
    
    def clean_response(self, response):
        """Clean and validate AI response"""
        response = response.strip()
        if not response.endswith(('.', '!', '?')):
            response += '।'
        if len(response) > 100:
            sentences = response.split('। ')
            response = sentences[0] + '।'
        return response

ai_agent = AIPhoneAgent()

@app.route('/webhook/voice', methods=['GET', 'POST'])
def handle_incoming_call():
    """Handle incoming phone calls"""
    call_sid = request.form.get('CallSid', 'unknown')
    from_number = request.form.get('From', 'unknown')
    
    response = VoiceResponse()
    welcome_message = "नमस्ते! मैं आपका AI सहायक हूँ। क्या बात करना चाहते हैं?"
    response.say(welcome_message, voice='Polly.Aditi', language='hi-IN')
    
    gather = Gather(
        input='speech',
        action=f'{NGROK_URL}/webhook/speech',
        method='POST',
        speech_timeout='auto',
        language='hi-IN',
        timeout=15
    )
    response.append(gather)
    response.say("कुछ नहीं सुना। दोबारा कॉल करें।", voice='Polly.Aditi', language='hi-IN')
    response.hangup()
    
    return Response(str(response), mimetype='text/xml')

@app.route('/webhook/speech', methods=['POST'])
def handle_speech():
    """Handle speech input from caller with SMS fallback"""
    call_sid = request.form.get('CallSid', 'unknown')
    speech_result = request.form.get('SpeechResult', '').strip()
    confidence = float(request.form.get('Confidence', '0'))
    from_number = request.form.get('From', 'unknown')
    
    response = VoiceResponse()
    
    if speech_result and len(speech_result.strip()) > 0:
        ai_response = ai_agent.generate_response(speech_result, call_sid)
        
        # Send response as SMS for clarity
        try:
            twilio_client.messages.create(
                body=f"AI जवाब: {ai_response}",
                from_=TWILIO_PHONE_NUMBER,
                to=from_number
            )
        except Exception as e:
            logger.error(f"Failed to send SMS: {str(e)}")
        
        response.say(ai_response, voice='Polly.Aditi', language='hi-IN', rate='medium')
        response.say("जवाब आपको मैसेज में भेजा। फिर से बोलें?", voice='Polly.Aditi', language='hi-IN')
        
        if should_continue_conversation(ai_response):
            gather = Gather(
                input='speech',
                action=f'{NGROK_URL}/webhook/speech',
                method='POST',
                speech_timeout='auto',
                language='hi-IN',
                timeout=20
            )
            response.append(gather)
            response.say("क्या आप अभी हैं? मैं सुन रहा हूँ...", voice='Polly.Aditi', language='hi-IN')
            response.redirect(f'{NGROK_URL}/webhook/timeout')
        else:
            response.say("बात करके अच्छा लगा! शानदार दिन बिताएं!", voice='Polly.Aditi', language='hi-IN')
            response.hangup()
    else:
        response.say("स्पष्ट नहीं सुना। धीरे या जोर से बोलें?", voice='Polly.Aditi', language='hi-IN')
        try:
            twilio_client.messages.create(
                body="स्पष्ट नहीं सुना। कृपया धीरे या जोर से बोलें।",
                from_=TWILIO_PHONE_NUMBER,
                to=from_number
            )
        except Exception as e:
            logger.error(f"Failed to send SMS: {str(e)}")
        
        gather = Gather(
            input='speech',
            action=f'{NGROK_URL}/webhook/speech',
            method='POST',
            speech_timeout='auto',
            language='hi-IN',
            timeout=15
        )
        response.append(gather)
        response.say("अभी भी नहीं सुना। दोबारा कॉल करें!", voice='Polly.Aditi', language='hi-IN')
        response.hangup()
    
    return Response(str(response), mimetype='text/xml')

@app.route('/webhook/partial', methods=['POST'])
def handle_partial():
    """Handle partial speech results"""
    return Response('', mimetype='text/xml')

@app.route('/webhook/timeout', methods=['POST'])
def handle_timeout():
    """Handle conversation timeout"""
    call_sid = request.form.get('CallSid', 'unknown')
    
    response = VoiceResponse()
    response.say("कॉल के लिए धन्यवाद! जल्द फिर बात करें। अलविदा!", voice='Polly.Aditi', language='hi-IN')
    response.hangup()
    
    if call_sid in conversations:
        del conversations[call_sid]
    
    return Response(str(response), mimetype='text/xml')

@app.route('/webhook/status', methods=['POST'])
def handle_status():
    """Handle call status updates"""
    call_sid = request.form.get('CallSid', 'unknown')
    call_status = request.form.get('CallStatus', 'unknown')
    
    if call_status in ['completed', 'failed', 'busy', 'no-answer']:
        if call_sid in conversations:
            del conversations[call_sid]
    
    return Response('OK', mimetype='text/plain')

def should_continue_conversation(ai_response):
    """Determine if conversation should continue"""
    end_phrases = [
        'अलविदा', 'बाय', 'कॉल खत्म', 'कॉल के लिए धन्यवाद', 'शानदार दिन बिताएं',
        'बाद में बात होगी', 'फिर मिलेंगे', 'ख्याल रखें'
    ]
    return not any(phrase in ai_response for phrase in end_phrases)

@app.route('/test-ai', methods=['POST'])
def test_ai_response():
    """Test AI response generation with conversation history"""
    try:
        data = request.get_json() or {}
        test_input = data.get('input', 'नमस्ते, आप कैसे हैं?')
        session_id = data.get('session_id', str(uuid.uuid4()))
        
        response = ai_agent.generate_response(test_input, session_id)
        
        history = conversations.get(session_id, [])
        formatted_history = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in history
        ]
        
        return {
            'success': True,
            'session_id': session_id,
            'input': test_input,
            'response': response,
            'conversation_history': formatted_history,
            'hf_available': hf_client is not None
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'hf_available': hf_client is not None
        }, 500

@app.route('/test-call', methods=['POST'])
def test_outbound_call():
    """Make a test outbound call"""
    try:
        data = request.get_json() or {}
        to_number = data.get('to', '+923398312724')
        
        call = twilio_client.calls.create(
            url=f'{NGROK_URL}/webhook/voice',
            to=to_number,
            from_=TWILIO_PHONE_NUMBER,
            method='POST',
            status_callback=f'{NGROK_URL}/webhook/status'
        )
        
        return {'success': True, 'call_sid': call.sid, 'message': 'Test call initiated - will connect to AI agent'}
        
    except Exception as e:
        logger.error(f"Test call failed: {str(e)}")
        return {'success': False, 'error': str(e)}, 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'active_conversations': len(conversations),
        'conversation_ids': list(conversations.keys()),
        'twilio_configured': bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
        'huggingface_configured': bool(HF_TOKEN),
        'huggingface_client_available': hf_client is not None,
        'ngrok_url': NGROK_URL,
        'phone_number': TWILIO_PHONE_NUMBER
    }

@app.route('/')
def home():
    """Home page with setup instructions and testing in English"""
    return f'''
    <h1>🤖 AI Phone Agent</h1>
    <p><strong>Status:</strong> Running ✅</p>
    <p><strong>Phone Number:</strong> {TWILIO_PHONE_NUMBER}</p>
    <p><strong>Webhook URL:</strong> {NGROK_URL}/webhook/voice</p>
    
    <h2>Quick Tests:</h2>
    <ul>
        <li><a href="/health">Health Check</a></li>
        <li><button onclick="testAI()">Test AI Response</button></li>
        <li><button onclick="testCall()">Test Outbound Call</button></li>
    </ul>
    
    <div id="test-results"></div>
    
    <h2>Setup Status:</h2>
    <ul>
        <li>Twilio: {'✅' if TWILIO_ACCOUNT_SID else '❌'}</li>
        <li>Hugging Face: {'✅' if HF_TOKEN else '❌'}</li>
        <li>HF Client: {'✅' if hf_client else '❌'}</li>
        <li>Ngrok: {'✅' if NGROK_URL != 'https://your-ngrok-url.ngrok.io' else '❌'}</li>
    </ul>
    
    <h2>Debug Info:</h2>
    <p>Active conversations: {len(conversations)}</p>
    
    <script>
    let sessionId = null;
    function testAI() {{
        const input = prompt("Enter test message:", "नमस्ते, आप कैसे हैं?");
        if (!input) return;
        
        const payload = {{input: input}};
        if (sessionId) payload.session_id = sessionId;
        
        fetch('/test-ai', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify(payload)
        }})
        .then(response => response.json())
        .then(data => {{
            const results = document.getElementById('test-results');
            if (data.success) {{
                sessionId = data.session_id;
                let historyHtml = '<h4>Conversation History:</h4><ul>';
                data.conversation_history.forEach(msg => {{
                    historyHtml += `<li><strong>${{msg.role}}:</strong> ${{msg.content}}</li>`;
                }});
                historyHtml += '</ul>';
                
                results.innerHTML = `
                    <h3>AI Test Results:</h3>
                    <p><strong>Session ID:</strong> ${{data.session_id}}</p>
                    <p><strong>Input:</strong> ${{data.input}}</p>
                    <p><strong>Response:</strong> ${{data.response}}</p>
                    <p><strong>HF Available:</strong> ${{data.hf_available}}</p>
                    ${{historyHtml}}
                `;
            }} else {{
                results.innerHTML = `<h3>AI Test Failed:</h3><p>${{data.error}}</p>`;
            }}
        }})
        .catch(error => {{
            document.getElementById('test-results').innerHTML = `<h3>Error:</h3><p>${{error}}</p>`;
        }});
    }}
    
    function testCall() {{
        fetch('/test-call', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{}})
        }})
        .then(response => response.json())
        .then(data => {{
            if (data.success) {{
                alert('Test call initiated! Your phone will ring and connect to the AI agent.');
            }} else {{
                alert('Test call failed: ' + data.error);
            }}
        }})
        .catch(error => alert('Error: ' + error));
    }}
    </script>
    '''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)