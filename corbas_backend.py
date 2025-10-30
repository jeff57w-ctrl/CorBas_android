"""
CorBas Backend - Real PyMUSAS + spaCy NLP Server + PDF Highlighting
====================================================================
This Flask server provides real linguistic tagging using PyMUSAS and spaCy,
plus accurate PDF highlighting using PyMuPDF.

Installation:
------------
pip install flask flask-cors spacy pymupdf
python -m spacy download en_core_web_sm
pip install pymusas

Run:
----
python corbas_backend.py

The server will run on http://localhost:5000
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import spacy
import fitz  # PyMuPDF
import io
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend

# Load spaCy model
print("Loading spaCy model...")
nlp = spacy.load("en_core_web_sm")

# Add PyMUSAS to spaCy pipeline with proper initialization
print("Loading PyMUSAS...")
HAS_PYMUSAS = False
try:
    from pymusas.rankers.lexicon_entry import ContextualRuleBasedRanker
    from pymusas.taggers.rules.single_word import SingleWordRule
    from pymusas.taggers.rules.mwe import MWERule
    from pymusas.pos_mapper import UPOS_TO_USAS_CORE
    
    print("Downloading PyMUSAS English lexicon...")
    import pymusas.lexicon_collection
    lexicon_lookup = pymusas.lexicon_collection.LexiconCollection.from_tsv(
        tsv_file_path=None,
        include_pos=True
    )
    
    ranker = ContextualRuleBasedRanker(*pymusas.rankers.lexicon_entry.ContextualRuleBasedRanker.get_construction_arguments(lexicon_lookup))
    
    single_word_rule = SingleWordRule(lexicon_lookup, ranker)
    mwe_rule = MWERule(lexicon_lookup, ranker)
    
    config = {
        "rules": [mwe_rule, single_word_rule],
        "ranker": ranker,
        "pos_mapper": UPOS_TO_USAS_CORE
    }
    
    nlp.add_pipe('pymusas_rule_based_tagger', config=config, last=True)
    HAS_PYMUSAS = True
    print("✓ PyMUSAS loaded successfully with English lexicon!")
    
except Exception as e:
    print(f"⚠ Warning: Could not load PyMUSAS properly: {e}")
    print("Continuing with spaCy-only tagging + fallback semantic tagger...")
    HAS_PYMUSAS = False

print("Backend ready!")
print(f"Pipelines loaded: {nlp.pipe_names}")


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok", 
        "message": "CorBas backend is running",
        "spacy": True,
        "pymusas": HAS_PYMUSAS,
        "pymupdf": True,
        "pipes": nlp.pipe_names
    })


@app.route('/analyze', methods=['POST'])
def analyze_text():
    """Analyze text with spaCy and PyMUSAS"""
    try:
        data = request.get_json()
        
        if not data or 'text' not in data:
            return jsonify({"error": "No text provided"}), 400
        
        text = data['text']
        corpus_name = data.get('corpus_name', 'unnamed')
        
        print(f"Analyzing text for corpus: {corpus_name} ({len(text)} chars)")
        
        doc = nlp(text)
        
        tokens = []
        
        for token in doc:
            if HAS_PYMUSAS and hasattr(token._, 'pymusas_tags'):
                semantic_tags = token._.pymusas_tags
                primary_semantic = semantic_tags[0] if semantic_tags else 'Z99'
            else:
                primary_semantic = get_semantic_fallback(token)
            
            token_data = {
                "word": token.text,
                "pos": token.pos_,
                "tag": token.tag_,
                "semantic": primary_semantic,
                "dep": token.dep_,
                "head": token.head.i,
                "lemma": token.lemma_,
                "is_stop": token.is_stop,
                "is_punct": token.is_punct
            }
            
            tokens.append(token_data)
        
        print(f"✓ Successfully analyzed {len(tokens)} tokens")
        
        return jsonify({
            "tokens": tokens,
            "num_tokens": len(tokens),
            "corpus_name": corpus_name,
            "has_pymusas": HAS_PYMUSAS
        })
    
    except Exception as e:
        print(f"✗ Error analyzing text: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/highlight_pdf', methods=['POST'])
def highlight_pdf():
    """Highlight phrases in a PDF using PyMuPDF"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        import json
        phrases_json = request.form.get('phrases', '[]')
        phrases = json.loads(phrases_json)
        
        if not phrases:
            return jsonify({"error": "No phrases to highlight"}), 400
        
        color_hex = request.form.get('color', '#FFFF00')
        color_hex = color_hex.lstrip('#')
        r = int(color_hex[0:2], 16) / 255
        g = int(color_hex[2:4], 16) / 255
        b = int(color_hex[4:6], 16) / 255
        
        print(f"Highlighting {len(phrases)} phrases in PDF: {file.filename}")
        
        pdf_bytes = file.read()
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        total_highlights = 0
        
        for page_num in range(len(pdf_document)):
            page = pdf_document[page_num]
            
            for phrase in phrases:
                phrase_lower = phrase.lower().strip()
                
                # Search case-insensitive
                text_instances = page.search_for(phrase_lower, flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES)
                text_instances.extend(page.search_for(phrase, flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES))
                
                for inst in text_instances:
                    highlight = page.add_highlight_annot(inst)
                    highlight.set_colors(stroke=(r, g, b))
                    highlight.set_opacity(0.4)
                    highlight.set_info(
                        title="CorBas",
                        content=f'"{phrase}"',
                        creationDate=datetime.now().strftime("%Y%m%d%H%M%S")
                    )
                    highlight.update()
                    total_highlights += 1
        
        print(f"✓ Successfully highlighted {total_highlights} occurrences")
        
        output_bytes = pdf_document.write()
        pdf_document.close()
        
        output = io.BytesIO(output_bytes)
        output.seek(0)
        
        original_name = file.filename.rsplit('.', 1)[0]
        output_filename = f"{original_name}_highlighted.pdf"
        
        return send_file(
            output,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=output_filename
        )
    
    except Exception as e:
        print(f"✗ Error highlighting PDF: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def get_semantic_fallback(token):
    """Fallback semantic tagger based on POS and word forms"""
    pos = token.pos_
    lemma = token.lemma_.lower()
    
    emotion_positive = {'happy', 'joy', 'delighted', 'pleased', 'excited', 'love', 'wonderful'}
    emotion_negative = {'sad', 'angry', 'fear', 'hate', 'anxious', 'worried', 'upset', 'depressed'}
    
    if lemma in emotion_positive:
        return 'E1.1+'
    if lemma in emotion_negative:
        return 'E1.1-'
    
    movement_verbs = {'go', 'come', 'move', 'walk', 'run', 'travel', 'arrive', 'leave', 'enter', 'exit'}
    if lemma in movement_verbs:
        return 'M1'
    
    speech_verbs = {'say', 'tell', 'speak', 'talk', 'communicate', 'discuss', 'mention', 'ask', 'answer'}
    if lemma in speech_verbs:
        return 'Q2.2'
    
    thought_verbs = {'think', 'believe', 'know', 'understand', 'consider', 'realize', 'remember', 'forget'}
    if lemma in thought_verbs:
        return 'X2.1'
    
    positive_adj = {'good', 'great', 'excellent', 'wonderful', 'amazing', 'beautiful', 'perfect', 'nice', 'fine'}
    negative_adj = {'bad', 'poor', 'terrible', 'awful', 'horrible', 'ugly', 'wrong', 'worse', 'worst'}
    
    if lemma in positive_adj:
        return 'A5.1+'
    if lemma in negative_adj:
        return 'A5.1-'
    
    time_words = {'today', 'tomorrow', 'yesterday', 'now', 'then', 'soon', 'later', 'before', 'after'}
    if lemma in time_words:
        return 'T1'
    
    place_words = {'here', 'there', 'where', 'place', 'location', 'home', 'school', 'office'}
    if lemma in place_words:
        return 'M7'
    
    if pos == 'NOUN':
        return 'O2'
    elif pos == 'PROPN':
        return 'Z3'
    elif pos == 'VERB':
        return 'A3+'
    elif pos == 'ADJ':
        return 'A5'
    elif pos == 'ADV':
        return 'A13'
    elif pos == 'NUM':
        return 'N1'
    elif pos == 'ADP':
        return 'Z5'
    elif pos == 'DET':
        return 'Z5'
    elif pos == 'PRON':
        return 'Z8'
    else:
        return 'Z99'


@app.route('/corbas.html')
def serve_html():
    """Serve the HTML file"""
    try:
        with open('corbas.html', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return """
        <html>
        <body style="font-family: Arial; padding: 40px; text-align: center;">
            <h1>⚠️ File Not Found</h1>
            <p>Please make sure <code>corbas.html</code> is in the same folder as <code>corbas_backend.py</code></p>
            <p><a href="/health">Check Backend Health</a></p>
        </body>
        </html>
        """


if __name__ == '__main__':
    print("\n" + "="*60)
    print("CorBas Backend Server")
    print("="*60)
    print("✓ Server running on: http://127.0.0.1:5000")
    print("✓ Open http://127.0.0.1:5000 in your browser")
    print("")
    print("Features:")
    print("  - Real spaCy NLP (POS tagging, dependency parsing)")
    if HAS_PYMUSAS:
        print("  - Real PyMUSAS semantic tagging (USAS categories)")
    else:
        print("  - Fallback semantic tagging")
    print("  - PDF Highlighting with PyMuPDF (accurate!)")
    print("")
    print("⚠ IMPORTANT: Keep this window open while using CorBas!")
    print("")
    print("Press Ctrl+C to stop")
    print("="*60 + "\n")
    
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)