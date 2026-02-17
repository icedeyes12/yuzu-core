# [FILE: web.py]
# [VERSION: 1.0.0.69.1]
# [DATE: 2025-08-12]
# [PROJECT: HKKM - Yuzu Companion]
# [DESCRIPTION: Web interface for AI companion system]
# [AUTHOR: Project Lead: Bani Baskara]
# [TEAM: Deepseek, GPT, Qwen, Aihara]
# [REPOSITORY: https://guthib.com/icedeyes12]
# [LICENSE: MIT]

from flask import Flask, render_template, request, jsonify, send_from_directory, session
import os
from datetime import datetime
from app import handle_user_message, start_session, end_session_cleanup, summarize_memory, summarize_global_player_profile
from app import get_available_providers, get_all_models, set_preferred_provider, get_vision_capabilities
from database import Database
from providers import get_ai_manager
from tools import multimodal_tools

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__,
    static_folder=os.path.join(BASE_DIR, 'static'),
    template_folder=os.path.join(BASE_DIR, 'templates')
)

app.secret_key = os.urandom(24)

print(f"Project directory: {BASE_DIR}")
print(f"Static folder: {app.static_folder}")
print(f"Templates folder: {app.template_folder}")

def ensure_static_dirs():
    static_dirs = [
        'static/uploads',
        'static/generated_images',
        'static/image_cache'
    ]
    
    for dir_path in static_dirs:
        os.makedirs(dir_path, exist_ok=True)
        print(f"Ensured directory: {dir_path}")

ensure_static_dirs()

@app.route('/')
def home():
    profile = Database.get_profile()
    return render_template('index.html', profile=profile)

@app.route('/dashboard')
def dashboard():
    profile = Database.get_profile()
    return render_template('dashboard.html', profile=profile)

@app.route('/chat')
def chat():
    # Gunakan Flask session instead of global variable
    if 'web_session_started' not in session:
        print("Flask session not found, starting new web session...")
        
        # Panggil fungsi start_session dari app.py - semua logika connection_msg sudah diurus di sana
        start_session(interface="web") 
        
        # Tandai session user ini sudah dimulai
        session['web_session_started'] = True
        print("Web session started and flagged in Flask session.")
    
    profile = Database.get_profile()
    return render_template('chat.html', profile=profile)

@app.route('/config')
def config():
    profile = Database.get_profile()
    return render_template('config.html', profile=profile)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/static/html/sidebar.html')
def serve_sidebar():
    try:
        return send_from_directory('templates', 'sidebar.html')
    except:
        return """
        <div class="sidebar" id="mainSidebar">
            <div class="sidebar-header">
                <h2>Yuzu Companion</h2>
                <button class="close-sidebar" onclick="toggleSidebar()">×</button>
            </div>
            <div class="sidebar-content">
                <div class="sidebar-section">
                    <h3>Navigation</h3>
                    <a href="/" class="sidebar-link">Home</a>
                    <a href="/chat" class="sidebar-link">Chat</a>
                    <a href="/config" class="sidebar-link">Config</a>
                    <a href="/about" class="sidebar-link">About</a>
                </div>
            </div>
        </div>
        """

@app.route('/api/get_profile')
def api_get_profile():
    try:
        profile = Database.get_profile()
        active_session = Database.get_active_session()
        
        chat_history = Database.get_chat_history(session_id=active_session['id'])
        
        session_memory = Database.get_session_memory(active_session['id'])
        
        ai_manager = get_ai_manager()
        available_providers = ai_manager.get_available_providers()
        all_models = ai_manager.get_all_models()
        
        providers_config = profile.get('providers_config', {})
        current_provider = providers_config.get('preferred_provider', 'ollama')
        current_model = providers_config.get('preferred_model', 'glm-4.6:cloud')
        
        api_keys = Database.get_api_keys()
        
        vision_capabilities = get_vision_capabilities()
        
        print(f"Sending profile data - Active Session: {active_session['id']}, History: {len(chat_history)} messages")
        
        return jsonify({
            **profile, 
            'chat_history': chat_history,
            'api_keys': api_keys,
            'active_session': active_session,
            'session_memory': session_memory,
            'ai_providers': {
                'available_providers': available_providers,
                'all_models': all_models,
                'current_provider': current_provider,
                'current_model': current_model
            },
            'multimodal_capabilities': vision_capabilities
        })
    except Exception as e:
        print(f"Error in api_get_profile: {e}")
        return jsonify({'error': 'Failed to load profile'}), 500

@app.route('/api/send_message', methods=['POST'])
def api_send_message():
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        
        if not user_message:
            return jsonify({'reply': 'Please type a message!'})
        
        print(f"Web message: {user_message[:200]}...")
        
        active_session = Database.get_active_session()
        session_id = active_session['id']
        
        ai_reply = handle_user_message(user_message, interface="web")
        
        print(f"AI reply: {ai_reply}")
        
        return jsonify({'reply': ai_reply})
        
    except Exception as e:
        print(f"Error in api_send_message: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'reply': 'Sorry, I encountered an error processing your message.'})

@app.route('/api/send_message_stream', methods=['POST'])
def api_send_message_stream():
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        
        if not user_message:
            def generate():
                yield 'data: {"chunk": "Please type a message!"}\n\n'
            return Response(generate(), mimetype='text/event-stream')
        
        print(f"Streaming message: {user_message[:200]}...")
        
        # Get streaming response generator from app.py
        response_generator = handle_user_message_streaming(
            user_message, 
            interface="web",
            provider=data.get('provider'),
            model=data.get('model')
        )
        
        def generate():
            for chunk in response_generator:
                if chunk:
                    yield f'data: {{"chunk": {json.dumps(chunk)}}}\n\n'
        
        return Response(generate(), mimetype='text/event-stream')
        
    except Exception as e:
        print(f"Error in streaming: {e}")
        import traceback
        traceback.print_exc()
        
        def generate_error():
            yield 'data: {"chunk": "Sorry, I encountered an error processing your message."}\n\n'
        
        return Response(generate_error(), mimetype='text/event-stream')
        
@app.route('/api/send_message_with_images', methods=['POST'])
def api_send_message_with_images():
    try:
        message_text = request.form.get('message', '').strip()
        image_files = request.files.getlist('images')
        
        if not message_text and not image_files:
            return jsonify({'reply': 'Please provide a message or images!'})
        
        print(f"Processing message with {len(image_files)} images")
        
        active_session = Database.get_active_session()
        session_id = active_session['id']
        
        saved_images = []
        image_markdowns = []
        
        for i, image_file in enumerate(image_files):
            if image_file and image_file.filename:
                uploads_dir = "static/uploads"
                os.makedirs(uploads_dir, exist_ok=True)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_filename = "".join(c for c in image_file.filename if c.isalnum() or c in ('.', '-', '_')).rstrip()
                filename = f"{timestamp}_{i}_{safe_filename}"
                filepath = os.path.join(uploads_dir, filename)
                
                image_file.save(filepath)
                
                web_url = f"/static/uploads/{filename}"
                
                image_markdown = f"![Uploaded Image](static/uploads/{filename})"
                image_markdowns.append(image_markdown)
                
                saved_images.append({
                    'web_url': web_url,
                    'filepath': filepath,
                    'markdown': image_markdown
                })
                print(f"Saved image to static: {filepath}")
        
        if image_markdowns:
            final_user_message = f"{message_text}\n\n" + "\n".join(image_markdowns) if message_text else "\n".join(image_markdowns)
        else:
            final_user_message = message_text
        
        print(f"Final user message: {final_user_message[:200]}...")
        
        ai_reply = handle_user_message(final_user_message, interface="web")
        
        return jsonify({
            'reply': ai_reply,
            'uploaded_images': saved_images
        })
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'reply': 'Error processing message.'})

@app.route('/api/generate_image', methods=['POST'])
def api_generate_image():
    try:
        data = request.get_json()
        prompt = data.get('prompt', '').strip()
        
        if not prompt:
            return jsonify({'error': 'Prompt required'}), 400
        
        print(f"Generating image with prompt: {prompt}")
        
        active_session = Database.get_active_session()
        session_id = active_session['id']
        
        Database.add_message('user', prompt, session_id=session_id)
        print(f"User image prompt saved to database")
        
        image_path, error = multimodal_tools.generate_image(prompt)
        
        if image_path:
            if image_path.startswith('static/generated_images/'):
                filename = os.path.basename(image_path)
                web_url = f"/static/generated_images/{filename}"
                image_markdown = f"![Generated Image](static/generated_images/{filename})"
            else:
                import shutil
                os.makedirs('static/generated_images', exist_ok=True)
                filename = os.path.basename(image_path)
                static_path = f"static/generated_images/{filename}"
                shutil.copy2(image_path, static_path)
                print(f"Copied {image_path} to {static_path}")
                
                web_url = f"/static/generated_images/{filename}"
                image_markdown = f"![Generated Image](static/generated_images/{filename})"
            
            ai_response = f"Image generated successfully! I've created your \"{prompt}\"\n\n{image_markdown}"
            
            Database.add_message('assistant', ai_response, session_id=session_id)
            print(f"AI image response with static path saved to database")
            
            return jsonify({
                'status': 'success',
                'image_url': web_url,
                'image_markdown': image_markdown,
                'prompt': prompt
            })
        else:
            error_msg = f"Image generation failed: {error}"
            Database.add_message('assistant', error_msg, session_id=session_id)
            return jsonify({'error': error}), 500
            
    except Exception as e:
        print(f"Error generating image: {e}")
        active_session = Database.get_active_session()
        Database.add_message('assistant', f"Error: {str(e)}", session_id=active_session['id'])
        return jsonify({'error': str(e)}), 500

@app.route('/static/generated_images/<filename>')
def serve_generated_image(filename):
    try:
        return send_from_directory('static/generated_images', filename)
    except FileNotFoundError:
        return jsonify({'error': 'Image not found'}), 404

@app.route('/static/uploads/<filename>')
def serve_uploaded_image(filename):
    try:
        return send_from_directory('static/uploads', filename)
    except FileNotFoundError:
        return jsonify({'error': 'Image not found'}), 404

@app.route('/api/get_vision_capabilities', methods=['GET'])
def api_get_vision_capabilities():
    try:
        capabilities = get_vision_capabilities()
        return jsonify({
            'status': 'success',
            'capabilities': capabilities
        })
    except Exception as e:
        print(f"Error getting vision capabilities: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/update_profile', methods=['POST'])
def api_update_profile():
    updates = request.get_json()
    Database.update_profile(updates)
    return jsonify({'status': 'success'})

@app.route('/api/clear_chat', methods=['POST'])
def api_clear_chat():
    active_session = Database.get_active_session()
    session_id = active_session['id']
    
    Database.clear_chat_history(session_id)
    
    # Reset session flag instead of global variable
    session.pop('web_session_started', None)
    return jsonify({'status': 'success'})

@app.route('/api/end_session', methods=['POST'])
def api_end_session():
    # Reset session flag instead of global variable
    session.pop('web_session_started', None)
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    profile = Database.get_profile()
    
    session_history = profile.get('session_history', {})
    current_session = session_history.get('current_session', {})
    start_time = current_session.get('start_time')
    duration = 0
    
    if start_time:
        try:
            start = datetime.fromisoformat(start_time)
            duration = (datetime.now() - start).total_seconds() / 60
        except:
            pass
    
    disconnect_msg = (
        f"*{profile['display_name']} disconnected from web interface at {current_time}. "
        f"Session duration: {duration:.1f} minutes*"
    )
    
    Database.add_message('system', disconnect_msg)
    end_session_cleanup(profile, interface="web", unexpected_exit=False)
    return jsonify({'status': 'session ended'})

@app.route('/api/add_api_key', methods=['POST'])
def api_add_api_key():
    data = request.get_json()
    key_name = data.get('key_name', '').strip()
    api_key = data.get('api_key', '').strip()
    
    if not api_key or not key_name:
        return jsonify({'status': 'error', 'message': 'Key name and API key required'})
    
    if Database.add_api_key(key_name, api_key):
        return jsonify({'status': 'success', 'message': f'{key_name} API key added'})
    else:
        return jsonify({'status': 'error', 'message': 'API key already exists or failed to save'})

@app.route('/api/add_chutes_key', methods=['POST'])
def api_add_chutes_key():
    try:
        data = request.get_json()
        api_key = data.get('api_key', '').strip()
        
        if not api_key:
            return jsonify({'status': 'error', 'message': 'Chutes API key required'})
        
        if Database.add_api_key('chutes', api_key):
            return jsonify({'status': 'success', 'message': 'Chutes API key added successfully!'})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to save Chutes API key'})
    except Exception as e:
        print(f"Error adding Chutes API key: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/remove_api_key', methods=['POST'])
def api_remove_api_key():
    data = request.get_json()
    key_name = data.get('key_name', '').strip()
    
    if not key_name:
        return jsonify({'status': 'error', 'message': 'Key name required'})
    
    if Database.remove_api_key(key_name):
        return jsonify({'status': 'success', 'message': f'{key_name} API key removed'})
    else:
        return jsonify({'status': 'error', 'message': 'API key not found'})

@app.route('/api/update_session_context', methods=['POST'])
def api_update_session_context():
    try:
        active_session = Database.get_active_session()
        session_id = active_session['id']
        profile = Database.get_profile()
        
        chat_history = Database.get_chat_history(session_id=session_id)
        
        if len(chat_history) < 5:
            return jsonify({'status': 'error', 'message': 'Need at least 5 conversation messages'})
        
        last_user_msg = next((msg for msg in reversed(chat_history) if msg['role'] == 'user'), None)
        last_ai_reply = next((msg for msg in reversed(chat_history) if msg['role'] == 'assistant'), None)
        
        if last_user_msg and last_ai_reply:
            success = summarize_memory(profile, last_user_msg['content'], last_ai_reply['content'], session_id)
            
            if success:
                session_memory = Database.get_session_memory(session_id)
                return jsonify({
                    'status': 'success',
                    'message': 'Session context updated!',
                    'session_memory': session_memory
                })
            else:
                return jsonify({'status': 'error', 'message': 'Session context update failed'})
        else:
            return jsonify({'status': 'error', 'message': 'Need conversation history'})
            
    except Exception as e:
        print(f"Error updating session context: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/update_global_profile', methods=['POST'])
def api_update_global_profile():
    try:
        success = summarize_global_player_profile()
        
        if success:
            profile = Database.get_profile()
            print(f"Returning updated profile with memory: {profile.get('memory', {})}")
            
            return jsonify({
                'status': 'success', 
                'message': 'Global player profile updated from ALL sessions!',
                'profile': profile
            })
        else:
            return jsonify({'status': 'error', 'message': 'Global profile analysis failed'})
    except Exception as e:
        print(f"Error updating global profile: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/rebuild_structured_memory', methods=['POST'])
def api_rebuild_structured_memory():
    """Rebuild structured memory from current session messages."""
    try:
        active_session = Database.get_active_session()
        session_id = active_session['id']

        from memory.extractor import process_messages_for_memory
        from memory.segmenter import segment_session

        # Extract semantic + episodic memories from recent messages
        recent = Database.get_chat_history(session_id=session_id, limit=50, recent=True)
        if len(recent) < 3:
            return jsonify({'status': 'error', 'message': 'Need at least 3 conversation messages to extract memory. Continue chatting and try again.'})

        process_messages_for_memory(session_id, recent)

        # Create conversation segments
        segment_count = segment_session(session_id)

        # Get current memory stats
        from database import get_db_session, SemanticMemory, EpisodicMemory, ConversationSegment
        with get_db_session() as db_session:
            semantic_count = db_session.query(SemanticMemory).filter_by(session_id=session_id).count()
            episodic_count = db_session.query(EpisodicMemory).filter_by(session_id=session_id).count()
            segment_total = db_session.query(ConversationSegment).filter_by(session_id=session_id).count()

        return jsonify({
            'status': 'success',
            'message': f'Structured memory rebuilt: {semantic_count} facts, {episodic_count} episodes, {segment_total} segments',
            'stats': {
                'semantic': semantic_count,
                'episodic': episodic_count,
                'segments': segment_total,
            }
        })
    except Exception as e:
        print(f"Error rebuilding structured memory: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/run_memory_decay', methods=['POST'])
def api_run_memory_decay():
    """Run FSRS-style decay on all memories for the current session."""
    try:
        active_session = Database.get_active_session()
        session_id = active_session['id']

        from memory.review import run_decay
        run_decay(session_id)

        return jsonify({
            'status': 'success',
            'message': 'Memory decay applied. Old memories faded, recent ones preserved.'
        })
    except Exception as e:
        print(f"Error running memory decay: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/memory_stats', methods=['GET'])
def api_memory_stats():
    """Get structured memory statistics for the current session."""
    try:
        active_session = Database.get_active_session()
        session_id = active_session['id']

        from database import get_db_session, SemanticMemory, EpisodicMemory, ConversationSegment
        with get_db_session() as db_session:
            semantic_count = db_session.query(SemanticMemory).filter_by(session_id=session_id).count()
            episodic_count = db_session.query(EpisodicMemory).filter_by(session_id=session_id).count()
            segment_count = db_session.query(ConversationSegment).filter_by(session_id=session_id).count()

            # Get top semantic facts for display
            top_facts = db_session.query(SemanticMemory).filter_by(
                session_id=session_id
            ).order_by(SemanticMemory.confidence.desc()).limit(10).all()

            facts_list = [
                f"{f.entity} {f.relation} {f.target}"
                for f in top_facts
            ]

        return jsonify({
            'status': 'success',
            'stats': {
                'semantic': semantic_count,
                'episodic': episodic_count,
                'segments': segment_count,
                'top_facts': facts_list,
            }
        })
    except Exception as e:
        print(f"Error getting memory stats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/providers/list', methods=['GET'])
def api_list_providers():
    try:
        ai_manager = get_ai_manager()
        available_providers = ai_manager.get_available_providers()
        all_models = ai_manager.get_all_models()
        
        profile = Database.get_profile()
        providers_config = profile.get('providers_config', {})
        current_provider = providers_config.get('preferred_provider', 'ollama')
        current_model = providers_config.get('preferred_model', 'glm-4.6:cloud')
        
        return jsonify({
            'status': 'success',
            'available_providers': available_providers,
            'all_models': all_models,
            'current_provider': current_provider,
            'current_model': current_model
        })
    except Exception as e:
        print(f"Error listing providers: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/providers/set_preferred', methods=['POST'])
def api_set_preferred_provider():
    try:
        data = request.get_json()
        provider_name = data.get('provider_name', '').strip()
        model_name = data.get('model_name', '').strip()
        
        if not provider_name:
            return jsonify({'status': 'error', 'message': 'Provider name required'})
        
        result = set_preferred_provider(provider_name, model_name)
        
        return jsonify({
            'status': 'success',
            'message': result
        })
    except Exception as e:
        print(f"Error setting preferred provider: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/providers/test_connection', methods=['POST'])
def api_test_provider_connection():
    try:
        data = request.get_json()
        provider_name = data.get('provider_name', '').strip()
        
        if not provider_name:
            return jsonify({'status': 'error', 'message': 'Provider name required'})
        
        ai_manager = get_ai_manager()
        provider = ai_manager.providers.get(provider_name)
        
        if not provider:
            return jsonify({'status': 'error', 'message': f'Provider {provider_name} not found'})
        
        is_connected = provider.test_connection()
        
        return jsonify({
            'status': 'success',
            'provider': provider_name,
            'connected': is_connected,
            'message': f'{provider_name}: {"Connected" if is_connected else "Connection failed"}'
        })
    except Exception as e:
        print(f"Error testing provider connection: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/browser_unload', methods=['POST'])
def api_browser_unload():
    # Reset session flag instead of global variable
    session.pop('web_session_started', None)
    print("Web page closed or refreshed - Flask session cleared")
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    profile = Database.get_profile()
    
    session_history = profile.get('session_history', {})
    current_session = session_history.get('current_session', {})
    start_time = current_session.get('start_time')
    duration = 0
    
    if start_time:
        try:
            start = datetime.fromisoformat(start_time)
            duration = (datetime.now() - start).total_seconds() / 60
        except:
            pass
    
    disconnect_msg = (
        f"*{profile['display_name']} disconnected unexpectedly from web interface at {current_time}. "
        f"Session duration: {duration:.1f} minutes*"
    )
    
    Database.add_message('system', disconnect_msg)
    end_session_cleanup(profile, interface="web", unexpected_exit=True)
    
    return jsonify({'status': 'page closed'})

@app.route('/api/sessions/list', methods=['GET'])
def api_list_sessions():
    try:
        sessions = Database.get_all_sessions()
        return jsonify({'sessions': sessions})
    except Exception as e:
        print(f"Error listing sessions: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/create', methods=['POST'])
def api_create_session():
    try:
        data = request.get_json()
        name = data.get('name', 'New Chat')
        
        session_id = Database.create_session(name)
        Database.switch_session(session_id)
        
        # Reset session flag instead of global variable
        session.pop('web_session_started', None)
        
        return jsonify({'status': 'success', 'session_id': session_id})
    except Exception as e:
        print(f"Error creating session: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/switch', methods=['POST'])
def api_switch_session():
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        
        if not session_id:
            return jsonify({'error': 'session_id required'}), 400
        
        Database.switch_session(session_id)
        
        # Reset session flag instead of global variable
        session.pop('web_session_started', None)
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        profile = Database.get_profile()
        
        all_sessions = Database.get_all_sessions()
        session_count = len(all_sessions)
        
        connection_msg = (
            f"*{profile['display_name']} connected to web interface at {current_time}. "
            f"Switched to session #{[s['id'] for s in all_sessions].index(session_id) + 1} of {session_count}*"
        )
        
        Database.add_message('system', connection_msg, session_id=session_id)
        
        # Set session flag for the new session
        session['web_session_started'] = True
        
        chat_history = Database.get_chat_history(session_id)
        session_memory = Database.get_session_memory(session_id)
        
        return jsonify({
            'status': 'success',
            'session_id': session_id,
            'chat_history': chat_history,
            'session_memory': session_memory
        })
    except Exception as e:
        print(f"Error switching session: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/rename', methods=['POST'])
def api_rename_session():
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        new_name = data.get('name')
        
        if not session_id or not new_name:
            return jsonify({'error': 'session_id and name required'}), 400
        
        success = Database.rename_session(session_id, new_name)
        
        if success:
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Session not found'}), 404
    except Exception as e:
        print(f"Error renaming session: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/delete', methods=['POST'])
def api_delete_session():
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        
        if not session_id:
            return jsonify({'error': 'session_id required'}), 400
        
        success = Database.delete_session(session_id)
        
        if success:
            active_session = Database.get_active_session()
            chat_history = Database.get_chat_history()
            session_memory = Database.get_session_memory(active_session['id'])
            
            return jsonify({
                'status': 'success',
                'active_session': active_session,
                'chat_history': chat_history,
                'session_memory': session_memory
            })
        else:
            return jsonify({'error': 'Session not found'}), 404
    except Exception as e:
        print(f"Error deleting session: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/<int:session_id>/memory', methods=['GET'])
def api_get_session_memory(session_id):
    try:
        session_memory = Database.get_session_memory(session_id)
        return jsonify({
            'status': 'success',
            'session_id': session_id,
            'session_context': session_memory.get('session_context', ''),
            'last_summarized': session_memory.get('last_summarized', 'Never')
        })
    except Exception as e:
        print(f"Error getting session memory: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/update_weather_location', methods=['POST'])
def api_update_weather_location():
    try:
        data = request.get_json()
        lat = float(data.get('lat', 0.0))
        lon = float(data.get('lon', 0.0))
        Database.update_profile({'weather_location': {'lat': lat, 'lon': lon}})
        return jsonify({'status': 'success', 'message': 'Weather location updated'})
    except Exception as e:
        print(f"Error updating weather location: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/global_knowledge/update', methods=['POST'])
def api_update_global_knowledge():
    try:
        data = request.get_json()
        facts = data.get('facts', '')
        
        global_knowledge = {'facts': facts}
        Database.update_profile({'global_knowledge': global_knowledge})
        
        return jsonify({'status': 'success', 'message': 'Global knowledge updated'})
    except Exception as e:
        print(f"Error updating global knowledge: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)