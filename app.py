from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import sqlite3
import base64
import requests
import json
import os
from datetime import datetime
import uuid
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Set limit to 16 MB
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Configuration
LC_API_KEY = os.environ.get('LC_API_KEY')
LC_API_URL = 'https://apis.languageconfidence.ai/speech-assessment/unscripted/us'

if not LC_API_KEY:
    print("Warning: LC_API_KEY not found in environment variables")

# Database initialization
def init_db():
    conn = sqlite3.connect('assessments.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            nik TEXT NOT NULL,
            question TEXT NOT NULL,
            audio_filename TEXT,
            predicted_text TEXT,
            overall_score REAL,
            pronunciation_score REAL,
            fluency_score REAL,
            grammar_score REAL,
            vocabulary_score REAL,
            ielts_prediction REAL,
            cefr_prediction TEXT,
            pte_prediction TEXT,
            content_relevance TEXT,
            content_relevance_feedback TEXT,
            assessment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            raw_response TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    name = request.form.get('name', '').strip()
    nik = request.form.get('nik', '').strip()
    
    if not name or not nik:
        return render_template('index.html', error='Nama dan NIK harus diisi')
    
    # Check if admin
    if name.lower() == 'admin' and nik.lower() == 'admin':
        session['is_admin'] = True
        return redirect(url_for('admin_dashboard'))
    
    # Regular user
    session['user_name'] = name
    session['user_nik'] = nik
    session['user_id'] = str(uuid.uuid4())
    session['is_admin'] = False
    
    return redirect(url_for('assessment'))

@app.route('/assessment')
def assessment():
    if 'user_name' not in session and not session.get('is_admin'):
        return redirect(url_for('index'))
    
    if session.get('is_admin'):
        return redirect(url_for('admin_dashboard'))
    
    return render_template('assessment.html', 
                         name=session['user_name'],
                         nik=session['user_nik'])

@app.route('/submit_assessment', methods=['POST'])
def submit_assessment():
    if 'user_name' not in session:
        return jsonify({'error': 'Session expired'}), 401
    
    try:
        data = request.get_json()
        audio_base64 = data.get('audio_base64')
        
        if not audio_base64:
            return jsonify({'error': 'Audio data required'}), 400
        
        # Prepare request to LC API
        lc_payload = {
            "audio_base64": audio_base64,
            "audio_format": "webm",
            "context": {
                "question": "What have you been doing at work this past week?",
                "context_description": "The user should talk about their work activities from the past week"
            }
        }
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'api-key': LC_API_KEY,
            'x-user-id': session['user_id']
        }
        
        # Call LC API
        response = requests.post(LC_API_URL, json=lc_payload, headers=headers)
        
        if response.status_code != 200:
            return jsonify({'error': f'API Error: {response.status_code}'}), 500
        
        lc_result = response.json()
        
        # Extract key metrics
        overall_score = lc_result.get('overall', {}).get('overall_score', 0)
        pronunciation_score = lc_result.get('pronunciation', {}).get('overall_score', 0)
        fluency_score = lc_result.get('fluency', {}).get('overall_score', 0)
        grammar_score = lc_result.get('grammar', {}).get('overall_score', 0)
        vocabulary_score = lc_result.get('vocabulary', {}).get('overall_score', 0)
        
        predicted_text = lc_result.get('metadata', {}).get('predicted_text', '')
        content_relevance = lc_result.get('metadata', {}).get('content_relevance', '')
        content_relevance_feedback = lc_result.get('metadata', {}).get('content_relevance_feedback', '')
        
        # Extract test predictions
        ielts_prediction = lc_result.get('overall', {}).get('english_proficiency_scores', {}).get('mock_ielts', {}).get('prediction', 0)
        cefr_prediction = lc_result.get('overall', {}).get('english_proficiency_scores', {}).get('mock_cefr', {}).get('prediction', '')
        pte_prediction = lc_result.get('overall', {}).get('english_proficiency_scores', {}).get('mock_pte', {}).get('prediction', '')
        
        # Save to database
        conn = sqlite3.connect('assessments.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO assessments 
            (user_id, name, nik, question, predicted_text, overall_score, 
             pronunciation_score, fluency_score, grammar_score, vocabulary_score,
             ielts_prediction, cefr_prediction, pte_prediction, 
             content_relevance, content_relevance_feedback, raw_response)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            session['user_id'], session['user_name'], session['user_nik'],
            "What have you been doing at work this past week?",
            predicted_text, overall_score, pronunciation_score, fluency_score,
            grammar_score, vocabulary_score, ielts_prediction, cefr_prediction,
            pte_prediction, content_relevance, content_relevance_feedback,
            json.dumps(lc_result)
        ))
        
        conn.commit()
        conn.close()
        
        # Return simplified results
        return jsonify({
            'success': True,
            'results': {
                'predicted_text': predicted_text,
                'overall_score': overall_score,
                'pronunciation_score': pronunciation_score,
                'fluency_score': fluency_score,
                'grammar_score': grammar_score,
                'vocabulary_score': vocabulary_score,
                'ielts_prediction': ielts_prediction,
                'cefr_prediction': cefr_prediction,
                'pte_prediction': pte_prediction,
                'content_relevance': content_relevance,
                'content_relevance_feedback': content_relevance_feedback
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('index'))
    
    # Ambil semua parameter filter dari URL
    name_filter = request.args.get('name_filter', '').strip()
    nik_filter = request.args.get('nik_filter', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    min_score = request.args.get('min_score', '').strip()
    max_score = request.args.get('max_score', '').strip()

    conn = sqlite3.connect('assessments.db')
    cursor = conn.cursor()
    
    # Bangun query SQL secara dinamis
    query = '''
        SELECT id, name, nik, predicted_text, overall_score, 
                pronunciation_score, fluency_score, grammar_score, vocabulary_score,
                ielts_prediction, cefr_prediction, content_relevance, assessment_date
        FROM assessments 
    '''
    params = []
    conditions = []

    if name_filter:
        conditions.append("name LIKE ?")
        params.append(f"%{name_filter}%")
    
    if nik_filter:
        conditions.append("nik LIKE ?")
        params.append(f"%{nik_filter}%")
    
    if start_date:
        conditions.append("DATE(assessment_date) >= ?")
        params.append(start_date)

    if end_date:
        conditions.append("DATE(assessment_date) <= ?")
        params.append(end_date)
    
    if min_score:
        try:
            conditions.append("overall_score >= ?")
            params.append(float(min_score))
        except ValueError:
            # Abaikan jika input bukan angka
            pass

    if max_score:
        try:
            conditions.append("overall_score <= ?")
            params.append(float(max_score))
        except ValueError:
            # Abaikan jika input bukan angka
            pass

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY assessment_date DESC"
    
    cursor.execute(query, params)
    assessments = cursor.fetchall()
    conn.close()
    
    return render_template('admin.html', assessments=assessments)

@app.route('/admin/detail/<int:assessment_id>')
def admin_detail(assessment_id):
    if not session.get('is_admin'):
        return redirect(url_for('index'))
    
    conn = sqlite3.connect('assessments.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM assessments WHERE id = ?', (assessment_id,))
    assessment = cursor.fetchone()
    conn.close()
    
    if not assessment:
        return redirect(url_for('admin_dashboard'))
    
    raw_response = {}
    if assessment[18]:  # raw_response berada di indeks ke-18
        try:
            raw_response = json.loads(assessment[18])
        except Exception as e:
            print(f"Error loading JSON: {e}") # Tambahan untuk melihat error
            pass

    # ---> TAMBAHKAN DUA BARIS INI <---
    print("----------- RAW RESPONSE DEBUG -----------")
    print(raw_response)
    # ----------------------------------------
    
    return render_template('admin_detail.html', assessment=assessment, raw_response=raw_response)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)