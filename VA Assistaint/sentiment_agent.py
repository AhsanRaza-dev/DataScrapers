import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, Response, jsonify, send_file, send_from_directory, redirect, url_for
from flask_cors import CORS
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client
from huggingface_hub import InferenceClient
import uuid
import re
import json

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Configuration
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
HF_TOKEN = os.getenv('HF_TOKEN')
NGROK_URL = os.getenv('NGROK_URL')

# Validate environment variables
if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, NGROK_URL]):
    logger.error("Missing required environment variables")
    raise ValueError("Please set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, and NGROK_URL in .env")

# Initialize clients
try:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    logger.info("Twilio client initialized successfully")
except Exception as e:
    logger.error(f"Twilio client error: {e}")
    exit(1)

# Initialize Hugging Face client
hf_client = None
if HF_TOKEN:
    try:
        hf_client = InferenceClient(
            provider="novita",
            api_key=HF_TOKEN,
        )
        test_response = hf_client.chat.completions.create(
            model="meta-llama/Llama-3.2-3B-Instruct",
            messages=[{"role": "user", "content": "Say hello"}],
            max_tokens=10,
            temperature=0.7
        )
        logger.info("Hugging Face client initialized and tested successfully")
    except Exception as e:
        logger.warning(f"Hugging Face client error: {e}")
        hf_client = None
else:
    logger.warning("HF_TOKEN not provided - LLM features will be disabled")

# Store conversations, sentiment data, and call history
conversations = {}
sentiment_data = {}
call_history = {}  # New dictionary to store ended calls

class LLMSentimentAnalyzer:
    def __init__(self, hf_client):
        self.hf_client = hf_client
        self.sentiment_system_prompt = """You are an expert sentiment analysis AI. Analyze the emotional tone and sentiment of the given text.

Your task is to:
1. Determine the overall sentiment (positive, negative, or neutral)
2. Identify specific emotions present (like frustration, happiness, confusion, urgency, etc.)
3. Rate the confidence of your analysis (0.0 to 1.0)
4. Provide a brief explanation

Respond ONLY in this exact JSON format:
{
    "sentiment": "positive/negative/neutral",
    "confidence": 0.85,
    "emotions": ["emotion1", "emotion2"],
    "explanation": "Brief explanation of the sentiment analysis",
    "intensity": "low/medium/high"
}

Be accurate and concise. Focus on the emotional content and tone of the message."""

    def analyze_text_sentiment(self, text):
        if not text or not self.hf_client:
            return self._create_fallback_sentiment('neutral', 0.5, 'No text or client available')
        
        try:
            messages = [
                {"role": "system", "content": self.sentiment_system_prompt},
                {"role": "user", "content": f"Analyze the sentiment of this text: '{text}'"}
            ]
            
            response = self.hf_client.chat.completions.create(
                model="meta-llama/Llama-3.2-3B-Instruct",
                messages=messages,
                max_tokens=150,
                temperature=0.3,
                top_p=0.9
            )
            
            ai_response = response.choices[0].message.content.strip()
            
            try:
                sentiment_result = json.loads(ai_response)
                if all(key in sentiment_result for key in ['sentiment', 'confidence', 'emotions']):
                    confidence = max(0.0, min(1.0, float(sentiment_result.get('confidence', 0.5))))
                    return {
                        'label': sentiment_result['sentiment'].lower(),
                        'confidence': round(confidence, 3),
                        'score': confidence,
                        'emotions': sentiment_result.get('emotions', []),
                        'explanation': sentiment_result.get('explanation', ''),
                        'intensity': sentiment_result.get('intensity', 'medium'),
                        'timestamp': datetime.now().isoformat(),
                        'method': 'llm_analysis'
                    }
                else:
                    logger.warning(f"Invalid sentiment analysis response format: {ai_response}")
                    return self._create_fallback_sentiment('neutral', 0.5, 'Invalid response format')
                    
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON sentiment response: {ai_response}")
                return self._extract_sentiment_from_text(ai_response, text)
                
        except Exception as e:
            logger.error(f"Error in LLM sentiment analysis: {str(e)}")
            return self._create_fallback_sentiment('neutral', 0.5, f'Analysis error: {str(e)}')
    
    def _extract_sentiment_from_text(self, ai_response, original_text):
        ai_response_lower = ai_response.lower()
        if any(word in ai_response_lower for word in ['positive', 'happy', 'good', 'pleased', 'satisfied']):
            sentiment = 'positive'
            confidence = 0.7
        elif any(word in ai_response_lower for word in ['negative', 'angry', 'frustrated', 'upset', 'sad']):
            sentiment = 'negative'
            confidence = 0.7
        else:
            sentiment = 'neutral'
            confidence = 0.6
        
        emotion_keywords = ['anger', 'frustration', 'happiness', 'sadness', 'confusion', 'excitement', 'stress', 'calm']
        detected_emotions = [emotion for emotion in emotion_keywords if emotion in ai_response_lower]
        
        return {
            'label': sentiment,
            'confidence': confidence,
            'score': confidence,
            'emotions': detected_emotions,
            'explanation': ai_response[:100] + '...' if len(ai_response) > 100 else ai_response,
            'intensity': 'medium',
            'timestamp': datetime.now().isoformat(),
            'method': 'llm_text_extraction'
        }
    
    def _create_fallback_sentiment(self, label, confidence, reason='Fallback analysis used'):
        return {
            'label': label,
            'confidence': round(confidence, 3),
            'score': confidence,
            'emotions': [],
            'explanation': reason,
            'intensity': 'medium',
            'timestamp': datetime.now().isoformat(),
            'method': 'fallback'
        }
    
    def analyze_conversation_sentiment(self, messages):
        if not messages or not self.hf_client:
            return self._create_fallback_sentiment('neutral', 0.5, 'No messages or client')
        
        try:
            user_messages = [msg['content'] for msg in messages if msg['role'] == 'user'][-5:]
            if not user_messages:
                return self._create_fallback_sentiment('neutral', 0.5, 'No user messages found')
            
            conversation_text = ' | '.join(user_messages)
            messages_for_analysis = [
                {"role": "system", "content": f"{self.sentiment_system_prompt}\n\nThis is for analyzing the overall sentiment of a conversation based on multiple user messages."},
                {"role": "user", "content": f"Analyze the overall sentiment progression in this conversation: '{conversation_text}'"}
            ]
            
            response = self.hf_client.chat.completions.create(
                model="meta-llama/Llama-3.2-3B-Instruct",
                messages=messages_for_analysis,
                max_tokens=150,
                temperature=0.3,
                top_p=0.9
            )
            
            ai_response = response.choices[0].message.content.strip()
            try:
                sentiment_result = json.loads(ai_response)
                confidence = max(0.0, min(1.0, float(sentiment_result.get('confidence', 0.5))))
                return {
                    'label': sentiment_result['sentiment'].lower(),
                    'confidence': round(confidence, 3),
                    'score': confidence,
                    'emotions': sentiment_result.get('emotions', []),
                    'explanation': sentiment_result.get('explanation', ''),
                    'intensity': sentiment_result.get('intensity', 'medium'),
                    'timestamp': datetime.now().isoformat(),
                    'method': 'llm_conversation_analysis'
                }
            except json.JSONDecodeError:
                return self._extract_sentiment_from_text(ai_response, conversation_text)
                
        except Exception as e:
            logger.error(f"Error in conversation sentiment analysis: {str(e)}")
            return self._create_fallback_sentiment('neutral', 0.5, f'Conversation analysis error: {str(e)}')

class AIPhoneAgent:
    def __init__(self):
        self.sentiment_analyzer = LLMSentimentAnalyzer(hf_client) if hf_client else None
        self.base_system_prompt = """You are a helpful AI phone assistant. 
        Keep responses concise, under 25 words. Be friendly and conversational. 
        Ask one clear question at a time. Speak naturally for phone calls.
        Always end with a follow-up question or invitation to continue."""
    
    def generate_response(self, user_input, call_sid):
        try:
            logger.info(f"Call {call_sid}: Generating response for input: '{user_input}'")
            if not user_input or len(user_input.strip()) < 1:
                logger.warning(f"Call {call_sid}: Empty user input, using fallback")
                return self.get_fallback_response("", error=False)
            
            if not hf_client:
                logger.info(f"Call {call_sid}: Using fallback response (no LLM client)")
                return self.get_fallback_response(user_input)
            
            if call_sid not in conversations:
                conversations[call_sid] = []
                logger.info(f"Call {call_sid}: Initialized conversation tracking")
                
            if call_sid not in sentiment_data:
                sentiment_data[call_sid] = {
                    'call_start': datetime.now().isoformat(),
                    'from_number': 'unknown',
                    'messages': [],
                    'overall_sentiment': 'neutral',
                    'sentiment_history': [],
                    'analysis_method': 'llm' if hf_client else 'fallback'
                }
                logger.info(f"Call {call_sid}: Initialized sentiment tracking")
            
            current_sentiment = None
            if self.sentiment_analyzer:
                try:
                    logger.info(f"Call {call_sid}: Starting sentiment analysis")
                    current_sentiment = self.sentiment_analyzer.analyze_text_sentiment(user_input)
                    if current_sentiment:
                        sentiment_data[call_sid]['messages'].append({
                            'text': user_input,
                            'sentiment': current_sentiment,
                            'timestamp': datetime.now().isoformat()
                        })
                        sentiment_data[call_sid]['sentiment_history'].append(current_sentiment)
                        overall_sentiment = self.sentiment_analyzer.analyze_conversation_sentiment(conversations[call_sid])
                        sentiment_data[call_sid]['overall_sentiment'] = overall_sentiment['label']
                        logger.info(f"Call {call_sid}: Sentiment: {current_sentiment['label']} (confidence: {current_sentiment['confidence']:.3f})")
                        logger.info(f"Call {call_sid}: Emotions: {current_sentiment['emotions']}")
                    else:
                        logger.warning(f"Call {call_sid}: Failed to get sentiment analysis result")
                except Exception as e:
                    logger.error(f"Call {call_sid}: Sentiment analysis error: {str(e)}")
                    current_sentiment = None
            
            conversations[call_sid].append({"role": "user", "content": user_input})
            system_prompt = self._create_sentiment_aware_prompt(current_sentiment)
            messages = [{"role": "system", "content": system_prompt}]
            recent_messages = conversations[call_sid][-6:]
            messages.extend(recent_messages)
            
            try:
                response = hf_client.chat.completions.create(
                    model="meta-llama/Llama-3.2-3B-Instruct",
                    messages=messages,
                    max_tokens=60,
                    temperature=0.8,
                    top_p=0.9,
                    frequency_penalty=0.1
                )
                ai_response = response.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"Call {call_sid}: AI generation error: {str(e)}")
                return self.get_fallback_response(user_input, error=True)
            
            if not ai_response or len(ai_response) < 3:
                logger.warning(f"Call {call_sid}: AI response too short, using fallback")
                return self.get_fallback_response(user_input)
            
            ai_response = self.clean_response(ai_response)
            conversations[call_sid].append({"role": "assistant", "content": ai_response})
            logger.info(f"Call {call_sid}: Generated response: '{ai_response}'")
            return ai_response
            
        except Exception as e:
            logger.error(f"Call {call_sid}: Critical error generating response: {str(e)}")
            return self.get_fallback_response(user_input, error=True)
    
    def _create_sentiment_aware_prompt(self, current_sentiment):
        base_prompt = self.base_system_prompt
        if not current_sentiment:
            return base_prompt
        
        sentiment_label = current_sentiment.get('label', 'neutral')
        emotions = current_sentiment.get('emotions', [])
        intensity = current_sentiment.get('intensity', 'medium')
        explanation = current_sentiment.get('explanation', '')
        
        if sentiment_label == 'negative':
            if 'frustration' in emotions or 'anger' in emotions:
                sentiment_instruction = f"""
                IMPORTANT: The user is showing {sentiment_label} sentiment with {intensity} intensity.
                Detected emotions: {', '.join(emotions)}
                AI Analysis: {explanation}
                
                Response Strategy: Be extra patient, empathetic, and calming. Acknowledge their frustration.
                Use phrases like "I understand this is frustrating" and focus on solutions.
                Speak in a slower, more reassuring tone."""
            elif 'sadness' in emotions or 'stress' in emotions:
                sentiment_instruction = f"""
                IMPORTANT: The user seems to be experiencing {sentiment_label} emotions with {intensity} intensity.
                Detected emotions: {', '.join(emotions)}
                AI Analysis: {explanation}
                
                Response Strategy: Show genuine empathy and support. Use comforting language.
                Offer help and reassurance. Be gentle and understanding."""
            else:
                sentiment_instruction = f"""
                IMPORTANT: The user has {sentiment_label} sentiment ({intensity} intensity).
                Detected emotions: {', '.join(emotions)}
                AI Analysis: {explanation}
                
                Response Strategy: Be supportive and understanding. Try to help improve their mood."""
        elif sentiment_label == 'positive':
            sentiment_instruction = f"""
            GREAT: The user is showing {sentiment_label} sentiment with {intensity} intensity!
            Detected emotions: {', '.join(emotions)}
            AI Analysis: {explanation}
            
            Response Strategy: Match their positive energy. Be enthusiastic and engaging.
            Build on their good mood while being helpful."""
        else:
            sentiment_instruction = f"""
            The user seems {sentiment_label} ({intensity} intensity).
            Detected emotions: {', '.join(emotions) if emotions else 'None specific'}
            AI Analysis: {explanation}
            
            Response Strategy: Provide balanced, helpful responses. Try to engage them positively."""
        
        if 'urgency' in emotions or 'emergency' in emotions:
            sentiment_instruction += "\n\nURGENT: The user needs immediate help. Prioritize quick, direct assistance."
        
        return f"{base_prompt}\n\nSentiment Analysis Context: {sentiment_instruction}"
    
    def get_fallback_response(self, user_input, error=False):
        if error:
            fallback_responses = [
                "I'm having a small technical issue, but I'm still here to help. What can I do for you?",
                "Sorry about that technical hiccup. Could you tell me what you need help with?",
                "I had a brief connection issue, but I'm back. How can I assist you today?"
            ]
            import random
            return random.choice(fallback_responses)
        
        if not user_input:
            return "Hello! I'm here to help you. What would you like to talk about?"
        
        user_lower = user_input.lower()
        fallback_patterns = {
            "hello": [
                "Hello! I'm here to help you. What's on your mind today?",
                "Hi there! Great to hear from you. What can I help you with?",
                "Hello! I'm your AI assistant. How can I make your day better?"
            ],
            "help": [
                "I'd be happy to help! What do you need assistance with?",
                "Absolutely! Tell me what you're looking for help with.",
                "I'm here to help. What's the challenge you're facing?"
            ],
            "thank": [
                "You're very welcome! Is there anything else I can help with?",
                "My pleasure! What else can I do for you today?",
                "You're so welcome! Any other questions for me?"
            ],
            "problem": [
                "I'd like to help you with that problem. Can you tell me more?",
                "Let's solve this together. What's the specific issue?",
                "I understand you're having a problem. Tell me more about it."
            ],
            "bye": [
                "Goodbye! It was wonderful talking with you!",
                "Take care! Feel free to call back anytime!",
                "Bye for now! Have a fantastic day!"
            ]
        }
        
        import random
        for pattern, responses in fallback_patterns.items():
            if pattern in user_lower:
                return random.choice(responses)
        
        generic_responses = [
            f"That's interesting! Can you tell me more about '{user_input}'?",
            f"I heard you mention '{user_input}'. What would you like to know about that?",
            f"Thanks for sharing that about '{user_input}'. How can I help you with it?",
            "I'm listening! Could you tell me a bit more so I can help you better?"
        ]
        
        return random.choice(generic_responses)
    
    def clean_response(self, response):
        if not response:
            return "I'm here to help! What would you like to talk about?"
        
        response = response.strip()
        response = re.sub(r'\*[^*]*\*', '', response)
        response = re.sub(r'[{}[\]]', '', response)
        response = re.sub(r'\s+', ' ', response)
        response = response.strip()
        
        if not response.endswith(('.', '!', '?')):
            response += '.'
        
        if len(response) > 150:
            sentences = response.split('. ')
            if len(sentences) > 1:
                response = sentences[0] + '.'
            else:
                response = response[:147] + '...'
        
        return response

ai_agent = AIPhoneAgent()

@app.route('/')
def home():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    try:
        try:
            return send_file('templates/index.html')
        except FileNotFoundError:
            try:
                return send_file('index.html')
            except FileNotFoundError:
                return '''
                <h1>Dashboard Not Found</h1>
                <p>Please ensure your dashboard HTML file is in one of these locations:</p>
                <ul>
                    <li>templates/index.html</li>
                    <li>index.html (same directory as this script)</li>
                </ul>
                <p><a href="/home">Go to system information page</a></p>
                '''
    except Exception as e:
        logger.error(f"Dashboard error: {str(e)}")
        return f'<h1>Error loading dashboard</h1><p>{str(e)}</p>'

@app.route('/static/<path:filename>')
def serve_static(filename):
    try:
        return send_from_directory('static', filename)
    except FileNotFoundError:
        return send_from_directory('.', filename)

@app.route('/home')
def home_page():
    dashboard_link = f'''
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 10px; margin: 20px 0;">
        <h2 style="color: white; margin: 0;">🚀 Access Your Dashboard</h2>
        <p style="color: rgba(255,255,255,0.9); margin: 10px 0;">View your beautiful AI Phone Agent Dashboard with real-time sentiment analysis</p>
        <a href="/dashboard" style="background: white; color: #667eea; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block;">
            Open Dashboard →
        </a>
    </div>
    '''
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI Phone Agent - LLM Sentiment Analysis</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
            .status {{ padding: 10px; margin: 10px 0; border-radius: 5px; }}
            .ok {{ background: #d4edda; border: 1px solid #c3e6cb; color: #155724; }}
            .error {{ background: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; }}
            .warning {{ background: #fff3cd; border: 1px solid #ffeaa7; color: #856404; }}
            ul {{ list-style-type: none; padding: 0; }}
            li {{ padding: 8px; margin: 5px 0; background: #f8f9fa; border-radius: 4px; }}
        </style>
    </head>
    <body>
        <h1>🤖 AI Phone Agent with LLM-Based Sentiment Analysis</h1>
        <p><a href="/dashboard" style="background: #667eea; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">← Back to Dashboard</a></p>
        
        {dashboard_link}
        
        <div class="status {'ok' if hf_client else 'warning'}">
            <strong>System Status:</strong> Running ✅<br>
            <strong>LLM Sentiment Analysis:</strong> {'✅ LLM-Powered (Llama-3.2-3B-Instruct)' if hf_client else '❌ LLM Unavailable (Fallback Mode)'}
        </div>
        
        <h2>📊 System Information</h2>
        <ul>
            <li><strong>Phone Number:</strong> {TWILIO_PHONE_NUMBER}</li>
            <li><strong>Webhook URL:</strong> {NGROK_URL}/webhook/voice</li>
            <li><strong>Active Conversations:</strong> {len(conversations)}</li>
            <li><strong>Active Sentiment Tracking:</strong> {len(sentiment_data)}</li>
            <li><strong>Historical Calls:</strong> {len(call_history)}</li>
            <li><strong>LLM Model:</strong> meta-llama/Llama-3.2-3B-Instruct</li>
        </ul>
        
        <h2>🔧 Configuration Status</h2>
        <ul>
            <li class="{'ok' if TWILIO_ACCOUNT_SID else 'error'}">Twilio Account: {'✅ Configured' if TWILIO_ACCOUNT_SID else '❌ Missing'}</li>
            <li class="{'ok' if TWILIO_AUTH_TOKEN else 'error'}">Twilio Auth: {'✅ Configured' if TWILIO_AUTH_TOKEN else '❌ Missing'}</li>
            <li class="{'ok' if HF_TOKEN else 'error'}">Hugging Face Token: {'✅ Configured' if HF_TOKEN else '❌ Missing'}</li>
            <li class="{'ok' if hf_client else 'error'}">LLM Client: {'✅ Connected' if hf_client else '❌ Failed'}</li>
            <li class="{'ok' if NGROK_URL != 'https://your-ngrok-url.ngrok.io' else 'error'}">Ngrok URL: {'✅ Configured' if NGROK_URL != 'https://your-ngrok-url.ngrok.io' else '❌ Update Required'}</li>
        </ul>
        
        <h2>🧪 Quick API Tests</h2>
        <ul>
            <li><a href="/health" target="_blank">Health Check API</a></li>
            <li><a href="/api/sentiment/analytics" target="_blank">Sentiment Analytics API</a></li>
            <li><a href="/api/call_history" target="_blank">Call History API</a></li>
            <li><button onclick="testSentiment()">Test LLM Sentiment Analysis</button></li>
            <li><button onclick="testAI()">Test AI Response with Sentiment</button></li>
            <li><button onclick="testCall()">Test Outbound Call</button></li>
        </ul>
        
        <div id="test-results" style="margin-top: 20px; padding: 15px; background: #f8f9fa; border-radius: 5px; display: none;">
            <h3>Test Results</h3>
            <div id="results-content"></div>
        </div>
        
        <script>
            function showResults(content) {{
                document.getElementById('results-content').innerHTML = content;
                document.getElementById('test-results').style.display = 'block';
            }}
            
            function testSentiment() {{
                const text = prompt("Enter text to analyze sentiment:", "I'm absolutely furious about this terrible service!");
                if (!text) return;
                
                fetch('/test-sentiment', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{text: text}})
                }})
                .then(response => response.json())
                .then(data => {{
                    if (data.success) {{
                        const sentiment = data.sentiment_analysis;
                        showResults(`
                            <h4>LLM Sentiment Analysis Result:</h4>
                            <p><strong>Input:</strong> "${{data.input_text}}"</p>
                            <p><strong>Sentiment:</strong> <span style="color: ${{sentiment.label === 'positive' ? 'green' : sentiment.label === 'negative' ? 'red' : 'blue'}}; font-weight: bold;">${{sentiment.label.toUpperCase()}}</span></p>
                            <p><strong>Confidence:</strong> ${{Math.round(sentiment.confidence * 100)}}%</p>
                            <p><strong>Emotions:</strong> ${{sentiment.emotions.join(', ') || 'None detected'}}</p>
                            <p><strong>Explanation:</strong> <em>"${{sentiment.explanation}}"</em></p>
                            <p><strong>Method:</strong> ${{sentiment.method}}</p>
                        `);
                    }} else {{
                        showResults(`<p style="color: red;"><strong>Error:</strong> ${{data.error}}</p>`);
                    }}
                }})
                .catch(error => showResults(`<p style="color: red;"><strong>Network Error:</strong> ${{error}}</p>`));
            }}
            
            function testAI() {{
                const input = prompt("Enter message for AI (try different emotions):", "I'm having a really bad day!");
                if (!input) return;
                
                fetch('/test-ai', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{input: input}})
                }})
                .then(response => response.json())
                .then(data => {{
                    if (data.success) {{
                        let content = `
                            <h4>AI Response Test with LLM Sentiment:</h4>
                            <p><strong>Your Input:</strong> "${{data.input}}"</p>
                            <p><strong>AI Response:</strong> "${{data.response}}"</p>
                            <p><strong>Session ID:</strong> ${{data.session_id}}</p>
                        `;
                        if (data.sentiment_analysis && data.sentiment_analysis.messages.length > 0) {{
                            const sentiment = data.sentiment_analysis.messages[data.sentiment_analysis.messages.length - 1].sentiment;
                            content += `
                                <h5>LLM Sentiment Analysis:</h5>
                                <p><strong>Detected Sentiment:</strong> ${{sentiment.label}} (${{Math.round(sentiment.confidence * 100)}}% confidence)</p>
                                <p><strong>Emotions:</strong> ${{sentiment.emotions.join(', ') || 'None'}}</p>
                                <p><strong>AI Explanation:</strong> <em>"${{sentiment.explanation}}"</em></p>
                            `;
                        }}
                        showResults(content);
                    }} else {{
                        showResults(`<p style="color: red;"><strong>Error:</strong> ${{data.error}}</p>`);
                    }}
                }})
                .catch(error => showResults(`<p style="color: red;"><strong>Network Error:</strong> ${{error}}</p>`));
            }}
            
            function testCall() {{
                const phone = prompt("Enter phone number (with country code):", "+1234567890");
                if (!phone) return;
                
                fetch('/api/call', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{to: phone}})
                }})
                .then(response => response.json())
                .then(data => {{
                    if (data.success) {{
                        showResults(`
                            <h4>Test Call Initiated!</h4>
                            <p><strong>Call SID:</strong> ${{data.call_sid}}</p>
                            <p><strong>Status:</strong> ${{data.message}}</p>
                            <p><strong>Note:</strong> Your phone should ring shortly with the AI agent featuring advanced LLM-based sentiment analysis.</p>
                        `);
                    }} else {{
                        showResults(`<p style="color: red;"><strong>Call Failed:</strong> ${{data.error}}</p>`);
                    }}
                }})
                .catch(error => showResults(`<p style="color: red;"><strong>Network Error:</strong> ${{error}}</p>`));
            }}
        </script>
        
        <footer style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; color: #666; text-align: center;">
            <p>&copy; 2025 AI Phone Agent Dashboard - Powered by Advanced LLM Sentiment Analysis</p>
            <p>Using meta-llama/Llama-3.2-3B-Instruct for intelligent emotion detection</p>
        </footer>
    </body>
    </html>
    '''

@app.route('/webhook/voice', methods=['GET', 'POST'])
def handle_incoming_call():
    try:
        call_sid = request.form.get('CallSid', 'unknown')
        from_number = request.form.get('From', 'unknown')
        
        logger.info(f"Call {call_sid}: Incoming call from {from_number}")
        
        sentiment_data[call_sid] = {
            'call_start': datetime.now().isoformat(),
            'from_number': from_number,
            'messages': [],
            'overall_sentiment': 'neutral',
            'sentiment_history': [],
            'analysis_method': 'llm' if hf_client else 'fallback'
        }
        
        conversations[call_sid] = []
        
        response = VoiceResponse()
        welcome_message = "Hello! I'm your AI assistant. I'm here to chat and help you today. What would you like to talk about?"
        
        response.say(welcome_message, voice='Polly.Joanna', language='en-US')
        
        gather = Gather(
            input='speech',
            action=f'{NGROK_URL}/webhook/speech',
            method='POST',
            speech_timeout='auto',
            language='en-US',
            timeout=10,
            partial_result_callback=f'{NGROK_URL}/webhook/partial'
        )
        response.append(gather)
        
        response.say("I didn't hear anything. Please speak up, or feel free to call back anytime!", voice='Polly.Joanna')
        response.hangup()
        
        logger.info(f"Call {call_sid}: Sent welcome message and waiting for speech")
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"Error in handle_incoming_call: {str(e)}")
        response = VoiceResponse()
        response.say("I'm sorry, there was a technical issue. Please try calling again in a moment.", voice='Polly.Joanna')
        response.hangup()
        return Response(str(response), mimetype='text/xml')

@app.route('/webhook/speech', methods=['POST'])
def handle_speech():
    try:
        call_sid = request.form.get('CallSid', 'unknown')
        speech_result = request.form.get('SpeechResult', '').strip()
        confidence = float(request.form.get('Confidence', '0'))
        
        logger.info(f"Call {call_sid}: Received speech: '{speech_result}' (confidence: {confidence})")
        
        response = VoiceResponse()
        
        if not speech_result or len(speech_result.strip()) < 2:
            logger.warning(f"Call {call_sid}: Speech too short or empty")
            response.say("I didn't catch that clearly. Could you please repeat what you said?", voice='Polly.Joanna')
            
            gather = Gather(
                input='speech',
                action=f'{NGROK_URL}/webhook/speech',
                method='POST',
                speech_timeout='auto',
                language='en-US',
                timeout=10
            )
            response.append(gather)
            response.say("I still can't hear you clearly. Feel free to call back anytime!", voice='Polly.Joanna')
            response.hangup()
            
            return Response(str(response), mimetype='text/xml')
        
        if confidence < 0.3:
            logger.warning(f"Call {call_sid}: Low confidence speech recognition: {confidence}")
            response.say("I'm having trouble understanding. Could you speak a bit more clearly?", voice='Polly.Joanna')
            
            gather = Gather(
                input='speech',
                action=f'{NGROK_URL}/webhook/speech',
                method='POST',
                speech_timeout='auto',
                language='en-US',
                timeout=10
            )
            response.append(gather)
            response.say("I'm still having trouble hearing you. Please try calling back!", voice='Polly.Joanna')
            response.hangup()
            
            return Response(str(response), mimetype='text/xml')
        
        try:
            ai_response = ai_agent.generate_response(speech_result, call_sid)
            
            if not ai_response or len(ai_response.strip()) < 3:
                logger.error(f"Call {call_sid}: AI response too short or empty")
                ai_response = "I'm here to help! What would you like to talk about?"
            
            logger.info(f"Call {call_sid}: Generated response: '{ai_response}'")
            
            if call_sid in sentiment_data and sentiment_data[call_sid].get('messages'):
                latest_sentiment = sentiment_data[call_sid]['messages'][-1]['sentiment']
                logger.info(f"Call {call_sid}: Latest sentiment - {latest_sentiment['label']} ({latest_sentiment['confidence']:.2f})")
            
            response.say(ai_response, voice='Polly.Joanna', language='en-US', rate='medium')
            
            if should_continue_conversation(ai_response):
                gather = Gather(
                    input='speech',
                    action=f'{NGROK_URL}/webhook/speech',
                    method='POST',
                    speech_timeout='auto',
                    language='en-US',
                    timeout=15
                )
                response.append(gather)
                response.say("I'm still here if you have more to share!", voice='Polly.Joanna')
                response.redirect(f'{NGROK_URL}/webhook/timeout')
            else:
                response.say("It was wonderful talking with you! Have a great day!", voice='Polly.Joanna')
                response.hangup()
                cleanup_call_data(call_sid)
            
        except Exception as e:
            logger.error(f"Call {call_sid}: Error generating AI response: {str(e)}")
            response.say("I'm having a small technical issue, but I'm still here. What can I help you with?", voice='Polly.Joanna')
            
            gather = Gather(
                input='speech',
                action=f'{NGROK_URL}/webhook/speech',
                method='POST',
                speech_timeout='auto',
                language='en-US',
                timeout=10
            )
            response.append(gather)
            response.say("I'm still having trouble. Feel free to call back anytime!", voice='Polly.Joanna')
            response.hangup()
            
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"Error in handle_speech: {str(e)}")
        response = VoiceResponse()
        response.say("I'm sorry, I encountered a technical issue. Please try calling again.", voice='Polly.Joanna')
        response.hangup()
        return Response(str(response), mimetype='text/xml')

@app.route('/webhook/partial', methods=['POST'])
def handle_partial():
    try:
        call_sid = request.form.get('CallSid', 'unknown')
        partial_result = request.form.get('UnstableSpeechResult', '')
        
        if partial_result:
            logger.info(f"Call {call_sid}: Partial speech: '{partial_result}'")
        
        return Response('', mimetype='text/xml')
    except Exception as e:
        logger.error(f"Error in handle_partial: {str(e)}")
        return Response('', mimetype='text/xml')

@app.route('/webhook/timeout', methods=['POST'])
def handle_timeout():
    try:
        call_sid = request.form.get('CallSid', 'unknown')
        logger.info(f"Call {call_sid}: Timeout reached")
        
        response = VoiceResponse()
        response.say("Thanks for calling! I hope we can chat again soon. Goodbye!", voice='Polly.Joanna')
        response.hangup()
        
        cleanup_call_data(call_sid)
        
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"Error in handle_timeout: {str(e)}")
        response = VoiceResponse()
        response.say("Goodbye!", voice='Polly.Joanna')
        response.hangup()
        return Response(str(response), mimetype='text/xml')

@app.route('/webhook/status', methods=['POST'])
def handle_status():
    try:
        call_sid = request.form.get('CallSid', 'unknown')
        call_status = request.form.get('CallStatus', 'unknown')
        
        logger.info(f"Call {call_sid}: Status update - {call_status}")
        
        if call_status in ['completed', 'failed', 'busy', 'no-answer', 'canceled']:
            cleanup_call_data(call_sid)
        
        return Response('OK', mimetype='text/plain')
        
    except Exception as e:
        logger.error(f"Error in handle_status: {str(e)}")
        return Response('ERROR', mimetype='text/plain')

def cleanup_call_data(call_sid):
    try:
        if call_sid in conversations and call_sid in sentiment_data:
            logger.info(f"Call {call_sid}: Moving data to call history")
            call_history[call_sid] = {
                'call_sid': call_sid,
                'conversation': conversations[call_sid],
                'sentiment_data': sentiment_data[call_sid],
                'call_end': datetime.now().isoformat(),
                'status': 'ended'
            }
            logger.info(f"Call {call_sid}: Final sentiment - {sentiment_data[call_sid].get('overall_sentiment', 'unknown')}")
            
            del conversations[call_sid]
            del sentiment_data[call_sid]
            
    except Exception as e:
        logger.error(f"Error cleaning up call data for {call_sid}: {str(e)}")

def should_continue_conversation(ai_response):
    if not ai_response:
        return True
    
    end_phrases = [
        'goodbye', 'bye', 'thank you for calling', 'have a great day',
        'have a wonderful day', 'that\'s all', 'nothing else', 'end call',
        'talk to you later', 'see you later', 'farewell', 'take care',
        'signing off', 'until next time', 'chat soon'
    ]
    
    ai_lower = ai_response.lower()
    return not any(phrase in ai_lower for phrase in end_phrases)

@app.route('/api/call', methods=['POST'])
def initiate_call():
    try:
        data = request.get_json() or {}
        to_number = data.get('to', '+923398312724')
        
        if not re.match(r'^\+\d{10,15}', to_number):
            return jsonify({'success': False, 'error': 'Invalid phone number format'}), 400
        
        call = twilio_client.calls.create(
            url=f'{NGROK_URL}/webhook/voice',
            to=to_number,
            from_=TWILIO_PHONE_NUMBER,
            method='POST',
            status_callback=f'{NGROK_URL}/webhook/status'
        )
        
        logger.info(f"Call initiated: SID {call.sid} to {to_number}")
        return jsonify({'success': True, 'call_sid': call.sid, 'message': 'Test call initiated - AI agent with LLM-based sentiment analysis'})
        
    except Exception as e:
        logger.error(f"Call initiation failed: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/sentiment/call/<call_sid>', methods=['GET'])
def get_call_sentiment_api(call_sid):
    try:
        logger.info(f"API request for call sentiment: {call_sid}")
        
        if call_sid not in sentiment_data and call_sid not in call_history:
            logger.warning(f"Call {call_sid} not found in sentiment_data or call_history")
            return jsonify({
                'error': 'Call not found',
                'call_sid': call_sid,
                'available_calls': list(sentiment_data.keys()) + list(call_history.keys())
            }), 404
        
        call_data = sentiment_data.get(call_sid, call_history.get(call_sid, {}).get('sentiment_data', {}))
        conversation = conversations.get(call_sid, call_history.get(call_sid, {}).get('conversation', []))
        
        llm_insights = {
            'emotions_detected': list(set([
                emotion for msg in call_data.get('messages', [])
                for emotion in msg.get('sentiment', {}).get('emotions', [])
            ])),
            'sentiment_progression': [
                {
                    'timestamp': msg['timestamp'],
                    'sentiment': msg['sentiment']['label'],
                    'confidence': msg['sentiment']['confidence'],
                    'explanation': msg['sentiment'].get('explanation', ''),
                    'emotions': msg['sentiment'].get('emotions', [])
                }
                for msg in call_data.get('messages', [])
            ],
            'analysis_quality': {
                'total_analyses': len(call_data.get('messages', [])),
                'avg_confidence': sum(msg['sentiment']['confidence'] for msg in call_data.get('messages', [])) / max(1, len(call_data.get('messages', []))),
                'method': call_data.get('analysis_method', 'unknown')
            }
        }
        
        result = {
            'call_sid': call_sid,
            'sentiment_data': call_data,
            'analysis_method': call_data.get('analysis_method', 'llm'),
            'message_count': len(call_data.get('messages', [])),
            'conversation': conversation,
            'conversation_length': len(conversation),
            'llm_insights': llm_insights,
            'success': True,
            'status': 'active' if call_sid in sentiment_data else 'ended'
        }
        
        logger.info(f"Returning call data for {call_sid}: {len(call_data.get('messages', []))} sentiment analyses, {len(conversation)} conversation messages")
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error getting call sentiment for {call_sid}: {str(e)}")
        return jsonify({
            'error': f'Internal server error: {str(e)}',
            'call_sid': call_sid,
            'success': False
        }), 500

@app.route('/api/call_history', methods=['GET'])
def get_call_history():
    try:
        logger.info("API request for call history")
        
        calls = []
        for call_sid, history_data in call_history.items():
            call_data = history_data['sentiment_data']
            conversation = history_data['conversation']
            
            llm_insights = {
                'emotions_detected': list(set([
                    emotion for msg in call_data.get('messages', [])
                    for emotion in msg.get('sentiment', {}).get('emotions', [])
                ])),
                'sentiment_progression': [
                    {
                        'timestamp': msg['timestamp'],
                        'sentiment': msg['sentiment']['label'],
                        'confidence': msg['sentiment']['confidence'],
                        'explanation': msg['sentiment'].get('explanation', ''),
                        'emotions': msg['sentiment'].get('emotions', [])
                    }
                    for msg in call_data.get('messages', [])
                ],
                'analysis_quality': {
                    'total_analyses': len(call_data.get('messages', [])),
                    'avg_confidence': sum(msg['sentiment']['confidence'] for msg in call_data.get('messages', [])) / max(1, len(call_data.get('messages', []))),
                    'method': call_data.get('analysis_method', 'unknown')
                }
            }
            
            calls.append({
                'call_sid': call_sid,
                'sentiment_data': call_data,
                'conversation': conversation,
                'call_end': history_data.get('call_end', 'unknown'),
                'status': history_data.get('status', 'ended'),
                'llm_insights': llm_insights
            })
        
        result = {
            'success': True,
            'calls': calls,
            'total_calls': len(calls),
            'llm_enabled': hf_client is not None
        }
        
        logger.info(f"Returning call history: {len(calls)} calls")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error getting call history: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Internal server error: {str(e)}'
        }), 500

@app.route('/api/sentiment/analytics', methods=['GET'])
def get_sentiment_analytics_api():
    try:
        total_calls = len(sentiment_data) + len(call_history)
        logger.info(f"Analytics request: {total_calls} total calls (active: {len(sentiment_data)}, historical: {len(call_history)})")
        
        if total_calls == 0:
            return jsonify({
                'message': 'No call data available',
                'total_calls': 0,
                'sentiment_distribution': {'positive': 0, 'neutral': 0, 'negative': 0},
                'emotion_distribution': {},
                'average_confidence': 0,
                'analysis_methods': {'llm': 0, 'fallback': 0},
                'active_calls': [],
                'historical_calls': [],
                'llm_enabled': hf_client is not None,
                'success': True
            })
        
        sentiment_counts = {'positive': 0, 'neutral': 0, 'negative': 0}
        emotion_counts = {}
        confidence_scores = []
        analysis_methods = {'llm': 0, 'fallback': 0}
        
        # Process active calls
        for call_sid, call_data in sentiment_data.items():
            overall_sentiment = call_data.get('overall_sentiment', 'neutral')
            sentiment_counts[overall_sentiment] = sentiment_counts.get(overall_sentiment, 0) + 1
            
            method = call_data.get('analysis_method', 'unknown')
            if method in analysis_methods:
                analysis_methods[method] += 1
            
            for message in call_data.get('messages', []):
                sentiment_info = message.get('sentiment', {})
                if 'confidence' in sentiment_info:
                    confidence_scores.append(sentiment_info['confidence'])
                for emotion in sentiment_info.get('emotions', []):
                    emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1
        
        # Process historical calls
        for call_sid, history_data in call_history.items():
            call_data = history_data['sentiment_data']
            overall_sentiment = call_data.get('overall_sentiment', 'neutral')
            sentiment_counts[overall_sentiment] = sentiment_counts.get(overall_sentiment, 0) + 1
            
            method = call_data.get('analysis_method', 'unknown')
            if method in analysis_methods:
                analysis_methods[method] += 1
            
            for message in call_data.get('messages', []):
                sentiment_info = message.get('sentiment', {})
                if 'confidence' in sentiment_info:
                    confidence_scores.append(sentiment_info['confidence'])
                for emotion in sentiment_info.get('emotions', []):
                    emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1
        
        avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0
        
        result = {
            'total_calls': total_calls,
            'sentiment_distribution': sentiment_counts,
            'emotion_distribution': emotion_counts,
            'average_confidence': round(avg_confidence, 3),
            'analysis_methods': analysis_methods,
            'active_calls': list(sentiment_data.keys()),
            'historical_calls': list(call_history.keys()),
            'llm_enabled': hf_client is not None,
            'total_messages_analyzed': len(confidence_scores),
            'success': True
        }
        
        logger.info(f"Analytics result: {total_calls} calls, {len(confidence_scores)} messages analyzed, avg confidence: {avg_confidence:.3f}")
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error getting sentiment analytics: {str(e)}")
        return jsonify({
            'error': f'Internal server error: {str(e)}',
            'success': False
        }), 500

@app.route('/sentiment/call/<call_sid>', methods=['GET'])
def get_call_sentiment(call_sid):
    return get_call_sentiment_api(call_sid)

@app.route('/sentiment/analytics', methods=['GET'])
def get_sentiment_analytics():
    return get_sentiment_analytics_api()

@app.route('/test-sentiment', methods=['POST'])
def test_sentiment_analysis():
    try:
        data = request.get_json() or {}
        test_text = data.get('text', 'I am really frustrated with this service!')
        
        if not hf_client:
            return jsonify({'error': 'LLM client not available'}), 500
        
        analyzer = LLMSentimentAnalyzer(hf_client)
        result = analyzer.analyze_text_sentiment(test_text)
        
        return jsonify({
            'success': True,
            'input_text': test_text,
            'sentiment_analysis': result,
            'analysis_method': result.get('method', 'unknown')
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/test-ai', methods=['POST'])
def test_ai_response():
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
        
        sentiment_info = sentiment_data.get(session_id, {})
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'input': test_input,
            'response': response,
            'conversation_history': formatted_history,
            'sentiment_analysis': sentiment_info,
            'llm_available': hf_client is not None,
            'analysis_method': sentiment_info.get('analysis_method', 'unknown')
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'llm_available': hf_client is not None
        }), 500

@app.route('/test-call', methods=['POST'])
def test_outbound_call():
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
        
        return jsonify({'success': True, 'call_sid': call.sid, 'message': 'Test call initiated - AI agent with LLM-based sentiment analysis'})
        
    except Exception as e:
        logger.error(f"Test call failed: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    try:
        active_conversations = len(conversations)
        active_sentiment_tracking = len(sentiment_data)
        historical_calls = len(call_history)
        conversation_ids = list(conversations.keys())
        sentiment_ids = list(sentiment_data.keys())
        history_ids = list(call_history.keys())
        
        missing_sentiment = [cid for cid in conversation_ids if cid not in sentiment_ids]
        missing_conversation = [sid for sid in sentiment_ids if sid not in conversation_ids]
        
        result = {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'active_conversations': active_conversations,
            'active_sentiment_tracking': active_sentiment_tracking,
            'historical_calls': historical_calls,
            'conversation_ids': conversation_ids,
            'sentiment_ids': sentiment_ids,
            'history_ids': history_ids,
            'twilio_configured': bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
            'huggingface_configured': bool(HF_TOKEN),
            'huggingface_client_available': hf_client is not None,
            'ngrok_url': NGROK_URL,
            'phone_number': TWILIO_PHONE_NUMBER,
            'sentiment_analysis_enabled': True,
            'sentiment_analysis_method': 'llm' if hf_client else 'fallback',
            'llm_model': 'meta-llama/Llama-3.2-3B-Instruct',
            'data_integrity': {
                'conversations_without_sentiment': missing_sentiment,
                'sentiment_without_conversations': missing_conversation,
                'data_sync_status': 'OK' if not missing_sentiment and not missing_conversation else 'WARNING'
            }
        }
        
        if sentiment_data or call_history:
            call_details = []
            for call_id, call_data in sentiment_data.items():
                call_details.append({
                    'call_id': call_id,
                    'message_count': len(call_data.get('messages', [])),
                    'overall_sentiment': call_data.get('overall_sentiment', 'unknown'),
                    'analysis_method': call_data.get('analysis_method', 'unknown'),
                    'call_start': call_data.get('call_start', 'unknown'),
                    'status': 'active'
                })
            for call_id, history_data in call_history.items():
                call_data = history_data['sentiment_data']
                call_details.append({
                    'call_id': call_id,
                    'message_count': len(call_data.get('messages', [])),
                    'overall_sentiment': call_data.get('overall_sentiment', 'unknown'),
                    'analysis_method': call_data.get('analysis_method', 'unknown'),
                    'call_start': call_data.get('call_start', 'unknown'),
                    'call_end': history_data.get('call_end', 'unknown'),
                    'status': 'ended'
                })
            result['call_details'] = call_details
        
        logger.info(f"Health check: {active_conversations} conversations, {active_sentiment_tracking} sentiment tracked, {historical_calls} historical calls")
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Health check error: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

if __name__ == '__main__':
    logger.info("Starting AI Phone Agent with enhanced error handling...")
    logger.info(f"Twilio Phone Number: {TWILIO_PHONE_NUMBER}")
    logger.info(f"Webhook URL: {NGROK_URL}/webhook/voice")
    logger.info(f"LLM Client Available: {hf_client is not None}")
    app.run(host='0.0.0.0', port=5000, debug=False)