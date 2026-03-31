import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client
from huggingface_hub import InferenceClient
from gradio_client import Client as GradioClient
import uuid
import tempfile
import base64
import requests
import io
import wave
import time
import sys

# Fix Windows console encoding issues
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())

# Load environment variables
load_dotenv()

# Configure logging with Windows compatibility
import sys

# Set up console handler with UTF-8 encoding for Windows
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

# Set up file handler
file_handler = logging.FileHandler('phone_agent.log', encoding='utf-8')
file_handler.setLevel(logging.INFO)

# Create formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    handlers=[console_handler, file_handler]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
HF_TOKEN = os.getenv('HF_TOKEN')
NGROK_URL = os.getenv('NGROK_URL')
VOICE_CLONE_URL = os.getenv('VOICE_CLONE_URL', 'http://192.168.1.3:7860/')

# Validate environment variables
if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, HF_TOKEN, NGROK_URL]):
    logger.error("Missing required environment variables")
    raise ValueError("Please set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, HF_TOKEN, and NGROK_URL in .env")

# Initialize clients with better error handling
twilio_client = None
hf_client = None
voice_clone_client = None

try:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    logger.info("Twilio client initialized successfully")
except Exception as e:
    logger.error(f"Twilio client initialization failed: {e}")

try:
    hf_client = InferenceClient(
        provider="novita",
        api_key=HF_TOKEN,
    )
    # Test the connection
    test_response = hf_client.chat.completions.create(
        model="meta-llama/Llama-3.2-3B-Instruct",
        messages=[{"role": "user", "content": "Say hello"}],
        max_tokens=10,
        temperature=0.7
    )
    logger.info("HuggingFace client initialized and tested successfully")
except Exception as e:
    logger.warning(f"HuggingFace client initialization failed: {e}")
    hf_client = None

try:
    voice_clone_client = GradioClient(VOICE_CLONE_URL)
    logger.info("Voice cloning client initialized successfully")
except Exception as e:
    logger.warning(f"Voice cloning client initialization failed: {e}")
    voice_clone_client = None

# Store conversations and voice profiles
conversations = {}
voice_profiles = {}

class VoiceCloningManager:
    def __init__(self):
        self.tts_model = "F5-TTS_v1"
        self.voice_samples = {}
        self.cloned_voices = {}
    
    def switch_tts_model(self, model_name="F5-TTS_v1"):
        """Switch TTS model with error handling"""
        try:
            if voice_clone_client:
                result = voice_clone_client.predict(
                    new_choice=model_name,
                    api_name="/switch_tts_model"
                )
                self.tts_model = model_name
                logger.info(f"Switched to TTS model: {model_name}")
                return True
            else:
                logger.warning("Voice clone client not available")
                return False
        except Exception as e:
            logger.error(f"Error switching TTS model: {e}")
            return False
    
    def save_voice_sample(self, call_sid, audio_url):
        """Download and save caller's voice sample with enhanced debugging"""
        try:
            if not audio_url:
                logger.warning("No audio URL provided for voice sample")
                return None
            
            logger.info(f"Downloading voice sample for call {call_sid} from: {audio_url}")
            
            # Add authentication for Twilio recording URLs
            auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            response = requests.get(audio_url, auth=auth, timeout=30)
            
            if response.status_code == 200:
                # Create temp file with proper audio format
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                    temp_file.write(response.content)
                    temp_path = temp_file.name
                
                # Verify the audio file
                file_size = os.path.getsize(temp_path)
                logger.info(f"Voice sample saved: {temp_path} ({file_size} bytes)")
                
                if file_size > 1000:  # Minimum reasonable audio file size
                    self.voice_samples[call_sid] = temp_path
                    return temp_path
                else:
                    logger.warning(f"Audio file too small ({file_size} bytes), might be invalid")
                    os.unlink(temp_path)
                    return None
            else:
                logger.error(f"Failed to download audio: HTTP {response.status_code}")
                logger.error(f"Response content: {response.text[:200]}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error saving voice sample: {e}")
        except Exception as e:
            logger.error(f"Error saving voice sample: {e}")
        return None
    
    def clone_voice_and_generate(self, call_sid, text, reference_audio_path=None):
        """Clone voice and generate speech using F5-TTS with enhanced error handling"""
        try:
            if not voice_clone_client:
                logger.warning("Voice cloning client not available")
                return None
            
            # Get reference audio path
            if not reference_audio_path and call_sid in self.voice_samples:
                reference_audio_path = self.voice_samples[call_sid]
            
            if not reference_audio_path or not os.path.exists(reference_audio_path):
                logger.warning(f"No valid reference audio available for call {call_sid}")
                return None
            
            logger.info(f"Starting voice cloning for call {call_sid}")
            logger.info(f"Reference audio: {reference_audio_path}")
            logger.info(f"Text to generate: '{text}'")
            logger.info(f"Using TTS model: {self.tts_model}")
            
            # Generate speech with voice cloning using F5-TTS
            result = voice_clone_client.predict(
                ref_audio_input=reference_audio_path,
                ref_text_input="",  # Let F5-TTS auto-transcribe the reference
                gen_text_input=text,  # This is the LLaMA response text
                model_type=self.tts_model,
                remove_silence=True,
                cross_fade_duration=0.15,
                speed=1.0,
                api_name="/infer"
            )
            
            logger.info(f"F5-TTS result type: {type(result)}")
            logger.info(f"F5-TTS result: {result}")
            
            # Handle different result formats from F5-TTS
            generated_audio_path = None
            if result:
                if isinstance(result, tuple):
                    # F5-TTS might return tuple (audio_path, other_info)
                    generated_audio_path = result[0]
                elif isinstance(result, list) and len(result) > 0:
                    # F5-TTS might return list [audio_path, ...]
                    generated_audio_path = result[0]
                elif isinstance(result, str):
                    # F5-TTS returns direct path
                    generated_audio_path = result
                else:
                    logger.warning(f"Unexpected F5-TTS result format: {result}")
            
            # Validate the generated audio file
            if generated_audio_path and os.path.exists(generated_audio_path):
                # Check if it's a valid audio file
                file_size = os.path.getsize(generated_audio_path)
                if file_size > 0:
                    # Store the cloned audio path for serving
                    self.cloned_voices[call_sid] = generated_audio_path
                    logger.info(f"Voice cloning successful! Generated audio: {generated_audio_path} ({file_size} bytes)")
                    return generated_audio_path
                else:
                    logger.warning(f"Generated audio file is empty: {generated_audio_path}")
            else:
                logger.warning(f"Generated audio file not found or invalid: {generated_audio_path}")
            
            return None
            
        except Exception as e:
            logger.error(f"Error in voice cloning for call {call_sid}: {str(e)}")
            logger.error(f"Exception details: {type(e).__name__}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    def cleanup_voice_data(self, call_sid):
        """Clean up stored voice data"""
        try:
            if call_sid in self.voice_samples:
                file_path = self.voice_samples[call_sid]
                if os.path.exists(file_path):
                    os.unlink(file_path)
                del self.voice_samples[call_sid]
                logger.info(f"Cleaned up voice sample for call {call_sid}")
            
            if call_sid in self.cloned_voices:
                del self.cloned_voices[call_sid]
                
        except Exception as e:
            logger.error(f"Error cleaning up voice data: {e}")

voice_manager = VoiceCloningManager()

class AIPhoneAgent:
    def __init__(self):
        self.system_prompt = """You are a helpful AI phone assistant with voice cloning capabilities. 
        Keep responses concise, under 25 words. Be friendly and conversational. 
        Ask one clear question at a time. Speak naturally for phone calls.
        Always end with a follow-up question or invitation to continue.
        You can adapt your voice to match the caller's accent and tone."""
        self.voice_cloning_enabled = {}
    
    def generate_response(self, user_input, call_sid):
        """Generate AI response with comprehensive error handling"""
        try:
            logger.info(f"Generating response for call {call_sid}: '{user_input}'")
            
            if not hf_client:
                logger.warning("HF client not available, using fallback")
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
                max_tokens=60,
                temperature=0.8,
                top_p=0.9,
                frequency_penalty=0.1
            )
            
            ai_response = response.choices[0].message.content.strip()
            
            if not ai_response or len(ai_response) < 3:
                logger.warning("Empty or too short AI response, using fallback")
                return self.get_fallback_response(user_input)
            
            ai_response = self.clean_response(ai_response)
            conversations[call_sid].append({"role": "assistant", "content": ai_response})
            
            logger.info(f"Generated response: '{ai_response}'")
            return ai_response
            
        except Exception as e:
            logger.error(f"Error generating AI response: {str(e)}")
            return self.get_fallback_response(user_input, error=True)
    
    def get_fallback_response(self, user_input, error=False):
        """Enhanced fallback responses"""
        if error:
            return "Sorry, I'm having trouble right now. Could you repeat that?"
        
        user_lower = user_input.lower()
        fallback_responses = {
            "hello": "Hello! I'm happy to chat with you. What's on your mind today?",
            "hi": "Hi there! How are you doing? What can I help you with?",
            "hey": "Hey! Great to hear from you. What would you like to talk about?",
            "help": "I'm here to help! What do you need assistance with?",
            "assist": "Of course! What can I assist you with today?",
            "weather": "I can't check weather right now, but how has your day been otherwise?",
            "time": "I can't tell the exact time, but I'm here to chat whenever you need. What's up?",
            "bye": "It was great talking with you! Have a wonderful day!",
            "thank": "You're very welcome! Is there anything else I can help with?",
            "how are you": "I'm doing well, thank you for asking! How are you doing today?",
            "voice": "I can adapt my voice to match yours! Just keep talking and I'll learn your accent.",
            "clone": "Voice cloning is enabled! I'm learning from your speech patterns right now.",
        }
        
        for key, response in fallback_responses.items():
            if key in user_lower:
                return response
        
        return f"I heard you mention something interesting. Can you tell me more about that?"
    
    def clean_response(self, response):
        """Clean and validate AI response"""
        response = response.strip()
        if not response.endswith(('.', '!', '?')):
            response += '.'
        if len(response) > 150:
            sentences = response.split('. ')
            response = sentences[0] + '.'
        return response
    
    def enable_voice_cloning(self, call_sid):
        """Enable voice cloning for a specific call"""
        self.voice_cloning_enabled[call_sid] = True
        logger.info(f"Voice cloning enabled for call {call_sid}")
    
    def is_voice_cloning_enabled(self, call_sid):
        """Check if voice cloning is enabled for a call"""
        return self.voice_cloning_enabled.get(call_sid, False)

ai_agent = AIPhoneAgent()

@app.route('/webhook/voice', methods=['GET', 'POST'])
def handle_incoming_call():
    """Handle incoming phone calls with comprehensive error handling"""
    try:
        # Log all request data for debugging
        logger.info(f"=== INCOMING CALL WEBHOOK ===")
        logger.info(f"Request method: {request.method}")
        logger.info(f"Request headers: {dict(request.headers)}")
        logger.info(f"Request form data: {dict(request.form)}")
        
        call_sid = request.form.get('CallSid', 'unknown')
        from_number = request.form.get('From', 'unknown')
        to_number = request.form.get('To', 'unknown')
        call_status = request.form.get('CallStatus', 'unknown')
        
        logger.info(f"Call from {from_number} to {to_number}, CallSid: {call_sid}, Status: {call_status}")
        
        # Validate required Twilio parameters
        if not call_sid or call_sid == 'unknown':
            logger.error("Missing CallSid in request")
            response = VoiceResponse()
            response.say("Sorry, there was a problem with your call.", voice='Polly.Joanna')
            response.hangup()
            return Response(str(response), mimetype='text/xml')
        
        response = VoiceResponse()
        welcome_message = "Hello! I'm your AI assistant with voice cloning capabilities. I can learn and adapt to your voice as we chat. What would you like to talk about?"
        
        response.say(welcome_message, voice='Polly.Joanna', language='en-US')
        
        # Enable voice cloning for this call
        ai_agent.enable_voice_cloning(call_sid)
        logger.info(f"Voice cloning enabled for call {call_sid}")
        
        # Set up speech gathering with recording for voice cloning
        gather = Gather(
            input='speech',
            action=f'{NGROK_URL}/webhook/speech',
            method='POST',
            speech_timeout='auto',
            language='en-US',
            timeout=15,
            record=True,  # Enable recording for voice cloning
            play_beep=False
        )
        response.append(gather)
        
        # Fallback if no speech detected
        response.say("I didn't hear anything. Please speak clearly, and I'll try to help you.", voice='Polly.Joanna')
        response.redirect(f'{NGROK_URL}/webhook/timeout')
        
        logger.info(f"Sending TwiML response for call {call_sid}")
        twiml_str = str(response)
        logger.info(f"TwiML Response: {twiml_str}")
        
        return Response(twiml_str, mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"CRITICAL ERROR in handle_incoming_call: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        
        # Return safe TwiML response
        try:
            response = VoiceResponse()
            response.say("Sorry, I'm having technical difficulties right now. Please try calling again in a few minutes.", 
                        voice='Polly.Joanna', language='en-US')
            response.hangup()
            return Response(str(response), mimetype='text/xml')
        except Exception as nested_e:
            logger.error(f"Failed to create error response: {nested_e}")
            # Return minimal valid TwiML
            return Response(
                '<?xml version="1.0" encoding="UTF-8"?><Response><Say voice="alice">Sorry, service unavailable.</Say><Hangup/></Response>',
                mimetype='text/xml'
            )

@app.route('/webhook/speech', methods=['POST'])
def handle_speech():
    """Handle speech input with enhanced voice cloning pipeline"""
    try:
        call_sid = request.form.get('CallSid', 'unknown')
        speech_result = request.form.get('SpeechResult', '').strip()
        confidence = float(request.form.get('Confidence', '0'))
        recording_url = request.form.get('RecordingUrl', '')
        
        logger.info(f"=== SPEECH PROCESSING START ===")
        logger.info(f"Call SID: {call_sid}")
        logger.info(f"Speech Result: '{speech_result}'")
        logger.info(f"Confidence: {confidence}")
        logger.info(f"Recording URL: {recording_url}")
        
        response = VoiceResponse()
        
        if speech_result and len(speech_result.strip()) > 0:
            
            # STEP 1: Save voice sample for cloning
            if recording_url and ai_agent.is_voice_cloning_enabled(call_sid):
                logger.info("=== VOICE SAMPLE COLLECTION ===")
                try:
                    saved_sample = voice_manager.save_voice_sample(call_sid, recording_url)
                    if saved_sample:
                        logger.info(f"Voice sample saved successfully: {saved_sample}")
                    else:
                        logger.warning("Failed to save voice sample")
                except Exception as e:
                    logger.warning(f"Voice sample collection failed: {e}")
            
            # STEP 2: Generate AI response using LLaMA
            logger.info("=== AI RESPONSE GENERATION ===")
            ai_response = ai_agent.generate_response(speech_result, call_sid)
            logger.info(f"LLaMA generated response: '{ai_response}'")
            
            # STEP 3: Clone voice with AI response
            logger.info("=== VOICE CLONING PIPELINE ===")
            cloned_audio = None
            if ai_agent.is_voice_cloning_enabled(call_sid):
                try:
                    logger.info("Attempting voice cloning with F5-TTS...")
                    cloned_audio = voice_manager.clone_voice_and_generate(call_sid, ai_response)
                    
                    if cloned_audio:
                        logger.info(f"Voice cloning SUCCESS: {cloned_audio}")
                    else:
                        logger.warning("Voice cloning FAILED - will use fallback TTS")
                        
                except Exception as e:
                    logger.error(f"Voice cloning ERROR: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
            
            # STEP 4: Use cloned voice or fallback to Twilio TTS
            logger.info("=== AUDIO PLAYBACK ===")
            if cloned_audio and os.path.exists(cloned_audio):
                try:
                    # Convert to proper format for Twilio if needed
                    audio_url = f"{NGROK_URL}/audio/{os.path.basename(cloned_audio)}"
                    response.play(audio_url)
                    logger.info(f"Playing cloned voice audio: {audio_url}")
                except Exception as e:
                    logger.warning(f"Failed to play cloned audio, using fallback TTS: {e}")
                    response.say(ai_response, voice='Polly.Joanna', language='en-US', rate='medium')
            else:
                logger.info("Using fallback Twilio TTS")
                response.say(ai_response, voice='Polly.Joanna', language='en-US', rate='medium')
            
            # Continue conversation or end call
            if should_continue_conversation(ai_response):
                gather = Gather(
                    input='speech',
                    action=f'{NGROK_URL}/webhook/speech',
                    method='POST',
                    speech_timeout='auto',
                    language='en-US',
                    timeout=20,
                    record=True  # Keep recording for continuous voice learning
                )
                response.append(gather)
                response.say("Are you still there? I'm listening...", voice='Polly.Joanna')
                response.redirect(f'{NGROK_URL}/webhook/timeout')
            else:
                response.say("It was wonderful talking with you! Have a great day!", voice='Polly.Joanna')
                response.hangup()
        else:
            # No speech detected
            logger.warning("No speech result received")
            response.say("I didn't catch that clearly. Could you please speak a bit louder or slower?", voice='Polly.Joanna')
            gather = Gather(
                input='speech',
                action=f'{NGROK_URL}/webhook/speech',
                method='POST',
                speech_timeout='auto',
                language='en-US',
                timeout=15,
                record=True
            )
            response.append(gather)
            response.say("I still can't hear you clearly. Feel free to call back anytime!", voice='Polly.Joanna')
            response.hangup()
        
        logger.info("=== SPEECH PROCESSING END ===")
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"CRITICAL ERROR in handle_speech: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Return safe response to prevent call failure
        response = VoiceResponse()
        response.say("Sorry, I encountered an error. Let me try again. What would you like to talk about?", voice='Polly.Joanna')
        
        gather = Gather(
            input='speech',
            action=f'{NGROK_URL}/webhook/speech',
            method='POST',
            speech_timeout='auto',
            language='en-US',
            timeout=15,
            record=True
        )
        response.append(gather)
        response.hangup()
        return Response(str(response), mimetype='text/xml')

@app.route('/webhook/timeout', methods=['POST'])
def handle_timeout():
    """Handle conversation timeout"""
    try:
        call_sid = request.form.get('CallSid', 'unknown')
        logger.info(f"Call timeout for {call_sid}")
        
        response = VoiceResponse()
        response.say("Thanks for calling! I hope we can chat again soon. Goodbye!", voice='Polly.Joanna')
        response.hangup()
        
        # Clean up
        if call_sid in conversations:
            del conversations[call_sid]
        
        voice_manager.cleanup_voice_data(call_sid)
        
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"Error in handle_timeout: {str(e)}")
        response = VoiceResponse()
        response.hangup()
        return Response(str(response), mimetype='text/xml')

@app.route('/webhook/status', methods=['POST'])
def handle_status():
    """Handle call status updates"""
    try:
        call_sid = request.form.get('CallSid', 'unknown')
        call_status = request.form.get('CallStatus', 'unknown')
        
        logger.info(f"Call status update: {call_sid} - {call_status}")
        
        if call_status in ['completed', 'failed', 'busy', 'no-answer']:
            if call_sid in conversations:
                del conversations[call_sid]
            voice_manager.cleanup_voice_data(call_sid)
        
        return Response('OK', mimetype='text/plain')
        
    except Exception as e:
        logger.error(f"Error in handle_status: {str(e)}")
        return Response('OK', mimetype='text/plain')

def should_continue_conversation(ai_response):
    """Determine if conversation should continue"""
    end_phrases = [
        'goodbye', 'bye', 'thank you for calling', 'have a great day',
        'have a wonderful day', 'that\'s all', 'nothing else', 'end call',
        'talk to you later', 'see you later', 'farewell', 'take care'
    ]
    return not any(phrase in ai_response.lower() for phrase in end_phrases)

@app.route('/test-ai', methods=['POST'])
def test_ai_response():
    """Test AI response generation"""
    try:
        data = request.get_json() or {}
        test_input = data.get('input', 'Hello, how are you?')
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
            'hf_available': hf_client is not None,
            'voice_cloning_available': voice_clone_client is not None
        }
    except Exception as e:
        logger.error(f"Error in test_ai_response: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'hf_available': hf_client is not None,
            'voice_cloning_available': voice_clone_client is not None
        }, 500

@app.route('/audio/<filename>')
def serve_audio(filename):
    """Serve generated audio files for Twilio playback"""
    try:
        # Look for the audio file in common locations
        audio_paths = [
            f"/tmp/{filename}",
            f"/tmp/gradio/{filename}",
            filename if os.path.exists(filename) else None
        ]
        
        # Find the actual file path
        audio_file = None
        for path in audio_paths:
            if path and os.path.exists(path):
                audio_file = path
                break
        
        # Also check stored cloned voices
        for call_sid, stored_path in voice_manager.cloned_voices.items():
            if filename in stored_path:
                audio_file = stored_path
                break
        
        if audio_file and os.path.exists(audio_file):
            logger.info(f"Serving audio file: {audio_file}")
            
            # Read the audio file
            with open(audio_file, 'rb') as f:
                audio_data = f.read()
            
            # Determine content type
            content_type = 'audio/wav'
            if filename.endswith('.mp3'):
                content_type = 'audio/mpeg'
            elif filename.endswith('.ogg'):
                content_type = 'audio/ogg'
            
            return Response(
                audio_data,
                mimetype=content_type,
                headers={
                    'Content-Disposition': f'inline; filename="{filename}"',
                    'Content-Length': str(len(audio_data)),
                    'Cache-Control': 'no-cache'
                }
            )
        else:
            logger.error(f"Audio file not found: {filename}")
            return Response('Audio file not found', status=404)
            
    except Exception as e:
        logger.error(f"Error serving audio file {filename}: {e}")
        return Response('Error serving audio', status=500)

@app.route('/test-voice-clone', methods=['POST'])
def test_voice_cloning():
    """Test voice cloning functionality with enhanced debugging"""
    try:
        data = request.get_json() or {}
        text = data.get('text', 'Hello, this is a test of voice cloning technology!')
        reference_audio = data.get('reference_audio_path')
        
        logger.info("=== VOICE CLONING TEST START ===")
        logger.info(f"Text: '{text}'")
        logger.info(f"Reference audio: {reference_audio}")
        
        if not reference_audio:
            return {
                'success': False,
                'error': 'No reference audio path provided'
            }, 400
        
        # Test F5-TTS connection first
        if not voice_clone_client:
            return {
                'success': False,
                'error': 'Voice cloning client not initialized'
            }, 500
        
        # Test voice cloning
        cloned_audio = voice_manager.clone_voice_and_generate('test', text, reference_audio)
        
        if cloned_audio:
            return {
                'success': True,
                'message': 'Voice cloning test successful',
                'cloned_audio_path': cloned_audio,
                'audio_url': f"{NGROK_URL}/audio/{os.path.basename(cloned_audio)}",
                'text': text,
                'reference_audio': reference_audio
            }
        else:
            return {
                'success': False,
                'error': 'Voice cloning failed - check logs for details'
            }, 500
            
    except Exception as e:
        logger.error(f"Voice cloning test error: {e}")
        return {
            'success': False,
            'error': str(e)
        }, 500

@app.route('/test-call', methods=['POST'])
def test_outbound_call():
    """Make a test outbound call"""
    try:
        data = request.get_json() or {}
        to_number = data.get('to', '+923398312724')  # Your default number
        
        if not twilio_client:
            return {'success': False, 'error': 'Twilio client not initialized'}, 500
        
        logger.info(f"Initiating test call to {to_number}")
        
        call = twilio_client.calls.create(
            url=f'{NGROK_URL}/webhook/voice',
            to=to_number,
            from_=TWILIO_PHONE_NUMBER,
            method='POST',
            status_callback=f'{NGROK_URL}/webhook/status'
        )
        
        logger.info(f"Test call created with SID: {call.sid}")
        
        return {
            'success': True, 
            'call_sid': call.sid, 
            'message': f'Test call initiated to {to_number}',
            'from_number': TWILIO_PHONE_NUMBER
        }
        
    except Exception as e:
        logger.error(f"Test call failed: {str(e)}")
        return {'success': False, 'error': str(e)}, 500

@app.route('/webhook/test', methods=['GET', 'POST'])
def test_webhook():
    """Test webhook endpoint to verify server is working"""
    try:
        logger.info("=== WEBHOOK TEST ===")
        logger.info(f"Method: {request.method}")
        logger.info(f"Headers: {dict(request.headers)}")
        if request.method == 'POST':
            logger.info(f"Form data: {dict(request.form)}")
            logger.info(f"JSON data: {request.get_json()}")
        
        response = VoiceResponse()
        response.say("Webhook test successful. Your server is working correctly.", voice='Polly.Joanna')
        response.hangup()
        
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"Webhook test error: {e}")
        return Response(
            '<?xml version="1.0" encoding="UTF-8"?><Response><Say>Test failed</Say></Response>',
            mimetype='text/xml'
        )

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'active_conversations': len(conversations),
        'conversation_ids': list(conversations.keys()),
        'active_voice_samples': len(voice_manager.voice_samples),
        'twilio_configured': bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
        'twilio_client_available': twilio_client is not None,
        'huggingface_configured': bool(HF_TOKEN),
        'huggingface_client_available': hf_client is not None,
        'voice_cloning_configured': bool(VOICE_CLONE_URL),
        'voice_cloning_available': voice_clone_client is not None,
        'current_tts_model': voice_manager.tts_model,
        'ngrok_url': NGROK_URL,
        'phone_number': TWILIO_PHONE_NUMBER,
        'voice_clone_url': VOICE_CLONE_URL
    }

@app.route('/')
def home():
    """Home page with setup instructions"""
    twilio_status = 'OK' if twilio_client else 'FAILED'
    hf_status = 'OK' if hf_client else 'FAILED'
    voice_status = 'OK' if voice_clone_client else 'FAILED'
    ngrok_status = 'OK' if NGROK_URL and 'ngrok' in NGROK_URL else 'FAILED'
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI Phone Agent with Voice Cloning</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background-color: #f5f5f5; }}
            .container {{ max-width: 800px; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            h1 {{ color: #333; }}
            .status {{ display: flex; align-items: center; margin: 10px 0; }}
            .status span {{ margin-left: 10px; }}
            button {{ background: #007bff; color: white; border: none; padding: 10px 20px; margin: 5px; border-radius: 5px; cursor: pointer; }}
            button:hover {{ background: #0056b3; }}
            .success {{ color: green; }}
            .error {{ color: red; }}
            #test-results {{ margin-top: 20px; padding: 15px; background: #f8f9fa; border-radius: 5px; }}
            .debug-info {{ background: #e9ecef; padding: 15px; margin-top: 20px; border-radius: 5px; font-size: 14px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 AI Phone Agent with Voice Cloning</h1>
            <p><strong>Status:</strong> <span class="success">Running ✅</span></p>
            <p><strong>Phone Number:</strong> {TWILIO_PHONE_NUMBER}</p>
            <p><strong>Webhook URL:</strong> {NGROK_URL}/webhook/voice</p>
            <p><strong>Current TTS Model:</strong> {voice_manager.tts_model}</p>
            
            <h2>🔧 Setup Status:</h2>
            <div class="status">
                <span>{twilio_status}</span>
                <span>Twilio Client</span>
            </div>
            <div class="status">
                <span>{hf_status}</span>
                <span>Hugging Face Client</span>
            </div>
            <div class="status">
                <span>{voice_status}</span>
                <span>Voice Cloning Server</span>
            </div>
            <div class="status">
                <span>{ngrok_status}</span>
                <span>Ngrok URL</span>
            </div>
            
            <h2>📊 Debug Info:</h2>
            <div class="debug-info">
                <p>Active conversations: {len(conversations)}</p>
                <p>Active voice samples: {len(voice_manager.voice_samples)}</p>
                <p>Voice Clone URL: {VOICE_CLONE_URL}</p>
                <p>Log file: phone_agent.log</p>
            </div>
            
            <h2>🧪 Quick Tests:</h2>
            <div>
                <button onclick="window.open('/health', '_blank')">Health Check</button>
                <button onclick="testAI()">Test AI Response</button>
                <button onclick="testCall()">Test Outbound Call</button>
                <button onclick="testWebhook()">Test Webhook</button>
            </div>
            
            <div id="test-results"></div>
            
            <h2>📋 Instructions:</h2>
            <ol>
                <li>Make sure all status indicators above are green ✅</li>
                <li>Configure your Twilio webhook URL to: <code>{NGROK_URL}/webhook/voice</code></li>
                <li>Test the system by calling your Twilio phone number: <strong>{TWILIO_PHONE_NUMBER}</strong></li>
                <li>Monitor logs in the console or check <code>phone_agent.log</code></li>
            </ol>
            
            <h2>🎯 Features:</h2>
            <ul>
                <li>✅ AI-powered conversations using LLaMA 3.2</li>
                <li>✅ Real-time voice cloning with F5-TTS</li>
                <li>✅ Twilio phone integration</li>
                <li>✅ Comprehensive error handling</li>
                <li>✅ Voice learning from caller's speech</li>
                <li>✅ Fallback TTS when voice cloning fails</li>
            </ul>
        </div>
        
        <script>
        function showResult(title, data, isError = false) {{
            const results = document.getElementById('test-results');
            const className = isError ? 'error' : 'success';
            const content = typeof data === 'object' ? JSON.stringify(data, null, 2) : data;
            results.innerHTML = `
                <h3 class="${{className}}">${{title}}</h3>
                <pre style="background: #f8f9fa; padding: 10px; border-radius: 5px; overflow-x: auto;">${{content}}</pre>
            `;
        }}
        
        function testAI() {{
            const input = prompt("Enter test message:", "Hello, can you clone my voice?");
            if (!input) return;
            
            fetch('/test-ai', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{input: input}})
            }})
            .then(response => response.json())
            .then(data => {{
                if (data.success) {{
                    showResult('✅ AI Test Results:', {{
                        input: data.input,
                        response: data.response,
                        hf_available: data.hf_available,
                        voice_cloning_available: data.voice_cloning_available,
                        session_id: data.session_id
                    }});
                }} else {{
                    showResult('❌ AI Test Failed:', data, true);
                }}
            }})
            .catch(error => {{
                showResult('❌ Error:', error.toString(), true);
            }});
        }}
        
        function testCall() {{
            const phoneNumber = prompt("Enter phone number to call:", "+923398312724");
            if (!phoneNumber) return;
            
            fetch('/test-call', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{to: phoneNumber}})
            }})
            .then(response => response.json())
            .then(data => {{
                if (data.success) {{
                    showResult('✅ Test Call Initiated:', {{
                        call_sid: data.call_sid,
                        to_number: phoneNumber,
                        from_number: data.from_number,
                        message: data.message
                    }});
                    alert('Test call initiated! The phone should ring shortly.');
                }} else {{
                    showResult('❌ Test Call Failed:', data, true);
                }}
            }})
            .catch(error => {{
                showResult('❌ Error:', error.toString(), true);
            }});
        }}
        
        function testWebhook() {{
            fetch('/webhook/test', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{test: true}})
            }})
            .then(response => response.text())
            .then(data => {{
                showResult('✅ Webhook Test Result:', data);
            }})
            .catch(error => {{
                showResult('❌ Webhook Test Failed:', error.toString(), true);
            }});
        }}
        
        // Auto-refresh status every 30 seconds
        setInterval(() => {{
            fetch('/health')
                .then(response => response.json())
                .then(data => {{
                    console.log('Health check:', data);
                }})
                .catch(error => {{
                    console.log('Health check failed:', error);
                }});
        }}, 30000);
        </script>
    </body>
    </html>
    '''

# Global error handler for webhooks
@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {str(e)}")
    import traceback
    logger.error(f"Traceback: {traceback.format_exc()}")
    
    # Check if this is a webhook request (should return TwiML)
    if request.path.startswith('/webhook/'):
        response = VoiceResponse()
        response.say("Sorry, I'm experiencing technical difficulties. Please try calling again later.", 
                    voice='Polly.Joanna', language='en-US')
        response.hangup()
        return Response(str(response), mimetype='text/xml')
    
    # For other requests, return JSON error
    return {
        'success': False,
        'error': 'Internal server error',
        'message': str(e)
    }, 500

# Add specific error handlers
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/webhook/'):
        response = VoiceResponse()
        response.say("Sorry, this service is not available.", voice='Polly.Joanna')
        response.hangup()
        return Response(str(response), mimetype='text/xml')
    return {'error': 'Not found'}, 404

@app.errorhandler(500)
def server_error(e):
    logger.error(f"Server error: {str(e)}")
    if request.path.startswith('/webhook/'):
        response = VoiceResponse()
        response.say("Sorry, I'm having technical problems. Please call back later.", voice='Polly.Joanna')
        response.hangup()
        return Response(str(response), mimetype='text/xml')
    return {'error': 'Server error'}, 500

def validate_configuration():
    """Validate configuration and log startup status"""
    logger.info("=== CONFIGURATION VALIDATION ===")
    
    issues = []
    
    # Check environment variables
    if not TWILIO_ACCOUNT_SID:
        issues.append("TWILIO_ACCOUNT_SID not set")
    if not TWILIO_AUTH_TOKEN:
        issues.append("TWILIO_AUTH_TOKEN not set")
    if not TWILIO_PHONE_NUMBER:
        issues.append("TWILIO_PHONE_NUMBER not set")
    if not HF_TOKEN:
        issues.append("HF_TOKEN not set")
    if not NGROK_URL or NGROK_URL == 'https://your-ngrok-url.ngrok.io':
        issues.append("NGROK_URL not properly configured")
    
    # Check client initialization
    if not twilio_client:
        issues.append("Twilio client failed to initialize")
    if not hf_client:
        issues.append("HuggingFace client failed to initialize")
    if not voice_clone_client:
        issues.append("Voice cloning client failed to initialize")
    
    # Log configuration status
    logger.info(f"Twilio Account SID: {TWILIO_ACCOUNT_SID[:10]}..." if TWILIO_ACCOUNT_SID else "Not set")
    logger.info(f"Twilio Phone Number: {TWILIO_PHONE_NUMBER}")
    logger.info(f"Ngrok URL: {NGROK_URL}")
    logger.info(f"Voice Clone URL: {VOICE_CLONE_URL}")
    logger.info(f"Twilio Client: {'OK' if twilio_client else 'FAILED'}")
    logger.info(f"HuggingFace Client: {'OK' if hf_client else 'FAILED'}")
    logger.info(f"Voice Clone Client: {'OK' if voice_clone_client else 'FAILED'}")
    
    if issues:
        logger.warning("Configuration issues found:")
        for issue in issues:
            logger.warning(f"  - {issue}")
    else:
        logger.info("All configuration checks passed")
    
    return len(issues) == 0

if __name__ == '__main__':
    logger.info("=== STARTING AI PHONE AGENT WITH VOICE CLONING ===")
    
    # Validate configuration
    config_ok = validate_configuration()
    
    if not config_ok:
        logger.warning("Configuration issues detected, but starting server anyway...")
    
    logger.info("Starting Flask server on 0.0.0.0:5000")
    logger.info(f"Webhook URL should be: {NGROK_URL}/webhook/voice")
    logger.info("=== SERVER STARTUP COMPLETE ===")
    
    app.run(host='0.0.0.0', port=5000, debug=False)