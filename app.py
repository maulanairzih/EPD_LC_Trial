from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
import base64
import requests
import json
import os
import uuid
from dotenv import load_dotenv
from sqlalchemy import desc

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB limit

# --- KONFIGURASI DATABASE BARU ---
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL').replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- MODEL DATABASE BARU (menggantikan CREATE TABLE) ---
class Assessment(db.Model):
    __tablename__ = 'assessments'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, nullable=False)
    name = db.Column(db.String, nullable=False)
    nik = db.Column(db.String, nullable=False)
    question = db.Column(db.String, nullable=False)
    predicted_text = db.Column(db.Text)
    overall_score = db.Column(db.Float)
    pronunciation_score = db.Column(db.Float)
    fluency_score = db.Column(db.Float)
    grammar_score = db.Column(db.Float)
    vocabulary_score = db.Column(db.Float)
    ielts_prediction = db.Column(db.Float)
    cefr_prediction = db.Column(db.String)
    pte_prediction = db.Column(db.String)
    content_relevance = db.Column(db.String)
    content_relevance_feedback = db.Column(db.Text)
    assessment_date = db.Column(db.DateTime, server_default=db.func.now())
    raw_response = db.Column(db.Text)

# --- FUNGSI UNTUK INISIALISASI DATABASE (JALANKAN SEKALI) ---
@app.route('/init-db')
def init_db_command():
    with app.app_context():
        db.create_all()
    return "Database tables created!"

# --- ROUTE YANG SUDAH ADA (TIDAK BERUBAH) ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    name = request.form.get('name', '').strip()
    nik = request.form.get('nik', '').strip()
    
    if not name or not nik:
        return render_template('index.html', error='Nama dan NIK harus diisi')
    
    if name.lower() == 'admin' and nik.lower() == 'admin':
        session['is_admin'] = True
        return redirect(url_for('admin_dashboard'))
    
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

# --- ROUTE SUBMIT DENGAN LOGIKA DATABASE BARU ---
@app.route('/submit_assessment', methods=['POST'])
def submit_assessment():
    if 'user_name' not in session:
        return jsonify({'error': 'Session expired'}), 401
    
    try:
        data = request.get_json()
        audio_base64 = data.get('audio_base64')
        
        # ... (Logika request ke API LC tetap sama) ...
        LC_API_KEY = os.environ.get('LC_API_KEY')
        LC_API_URL = 'https://apis.languageconfidence.ai/speech-assessment/unscripted/us'
        
        lc_payload = {
            "audio_base64": audio_base64, "audio_format": "webm",
            "context": {
                "question": "What have you been doing at work this past week?",
                "context_description": "The user should talk about their work activities from the past week"
            }
        }
        headers = {
            'Content-Type': 'application/json', 'Accept': 'application/json',
            'api-key': LC_API_KEY, 'x-user-id': session['user_id']
        }
        response = requests.post(LC_API_URL, json=lc_payload, headers=headers)
        
        if response.status_code != 200:
            return jsonify({'error': f'API Error: {response.status_code} - {response.text}'}), 500
        
        lc_result = response.json()
        
        # Simpan ke database menggunakan SQLAlchemy
        new_assessment = Assessment(
            user_id=session['user_id'],
            name=session['user_name'],
            nik=session['user_nik'],
            question="What have you been doing at work this past week?",
            predicted_text=lc_result.get('metadata', {}).get('predicted_text', ''),
            overall_score=lc_result.get('overall', {}).get('overall_score', 0),
            pronunciation_score=lc_result.get('pronunciation', {}).get('overall_score', 0),
            fluency_score=lc_result.get('fluency', {}).get('overall_score', 0),
            grammar_score=lc_result.get('grammar', {}).get('overall_score', 0),
            vocabulary_score=lc_result.get('vocabulary', {}).get('overall_score', 0),
            ielts_prediction=lc_result.get('overall', {}).get('english_proficiency_scores', {}).get('mock_ielts', {}).get('prediction', 0),
            cefr_prediction=lc_result.get('overall', {}).get('english_proficiency_scores', {}).get('mock_cefr', {}).get('prediction', ''),
            pte_prediction=lc_result.get('overall', {}).get('english_proficiency_scores', {}).get('mock_pte', {}).get('prediction', ''),
            content_relevance=lc_result.get('metadata', {}).get('content_relevance', ''),
            content_relevance_feedback=lc_result.get('metadata', {}).get('content_relevance_feedback', ''),
            raw_response=json.dumps(lc_result)
        )
        db.session.add(new_assessment)
        db.session.commit()
        
        # ... (Return simplified results tetap sama) ...
        return jsonify({
            'success': True,
            'results': {
                'predicted_text': new_assessment.predicted_text,
                'overall_score': new_assessment.overall_score,
                'pronunciation_score': new_assessment.pronunciation_score,
                'fluency_score': new_assessment.fluency_score,
                'grammar_score': new_assessment.grammar_score,
                'vocabulary_score': new_assessment.vocabulary_score,
                'ielts_prediction': new_assessment.ielts_prediction,
                'cefr_prediction': new_assessment.cefr_prediction,
                'pte_prediction': new_assessment.pte_prediction,
                'content_relevance': new_assessment.content_relevance,
                'content_relevance_feedback': new_assessment.content_relevance_feedback
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# --- ROUTE ADMIN DENGAN LOGIKA DATABASE BARU ---
@app.route('/admin')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('index'))
    
    query = Assessment.query

    # Logika filter tetap sama, hanya cara query-nya yang berubah
    name_filter = request.args.get('name_filter', '').strip()
    if name_filter:
        query = query.filter(Assessment.name.ilike(f"%{name_filter}%"))
    
    # ... (Tambahkan filter lain di sini jika perlu, dengan cara yang sama) ...

    assessments = query.order_by(desc(Assessment.assessment_date)).all()
    
    return render_template('admin.html', assessments=assessments)

@app.route('/admin/detail/<int:assessment_id>')
def admin_detail(assessment_id):
    if not session.get('is_admin'):
        return redirect(url_for('index'))
    
    assessment = db.session.get(Assessment, assessment_id)
    if not assessment:
        return redirect(url_for('admin_dashboard'))

    raw_response = json.loads(assessment.raw_response) if assessment.raw_response else {}
    
    return render_template('admin_detail.html', assessment=assessment, raw_response=raw_response)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all() # Untuk membuat DB saat dijalankan lokal
    app.run(debug=True)