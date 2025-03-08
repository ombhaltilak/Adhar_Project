from flask import Flask, request, jsonify, send_from_directory
import os
import zipfile
import pandas as pd
import cv2
import re
from ultralytics import YOLO
import easyocr
from flask_cors import CORS
import logging
import shutil
import google.generativeai as genai
import time
import requests
from fuzzywuzzy import fuzz, process

# Flask app setup
app = Flask(__name__)
CORS(app, resources={r"/process-files": {"origins": "http://localhost:8000"}})

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables (set in Vercel dashboard)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CLASS_MODEL_PATH = os.getenv("CLASS_MODEL_PATH", "models/classification_best.pt")
DETECT_MODEL_PATH = os.getenv("DETECT_MODEL_PATH", "models/detection_best.pt")
NODEJS_URL = os.getenv("NODEJS_URL", "https://your-nodejs-app.vercel.app/store-results")
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", 5000))

# Validate critical environment variables
if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY not set in Vercel environment variables")
    raise ValueError("GEMINI_API_KEY is required")

if not all(os.path.exists(p) for p in [CLASS_MODEL_PATH, DETECT_MODEL_PATH]):
    logger.error(f"Model files missing: CLASS={CLASS_MODEL_PATH}, DETECT={DETECT_MODEL_PATH}")
    raise FileNotFoundError("Model files missing or incorrect paths in Vercel environment variables!")

# Initialize models and APIs
genai.configure(api_key=GEMINI_API_KEY)
classification_model = YOLO(CLASS_MODEL_PATH)
detection_model = YOLO(DETECT_MODEL_PATH)
reader = easyocr.Reader(['en'], gpu=False)

# Indian states list
states = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
    "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal"
]

# [Rest of the functions (parse_address, classify_image, extract_text, calculate_match_score_api, calculate_score) remain unchanged]
# Copy the same function definitions as in your original code here.

def parse_address(address):
    # ... (same as original)
    pass

def classify_image(image_path):
    # ... (same as original)
    pass

def extract_text(image_path):
    # ... (same as original)
    pass

def calculate_match_score_api(extracted_text, excel_text, retries=3, delay=2, field_type="text"):
    # ... (same as original)
    pass

def calculate_score(extracted, excel):
    # ... (same as original)
    pass

@app.route('/process-files', methods=['POST'])
def process_files():
    # ... (same as original, but update NODEJS_URL if needed)
    try:
        logger.info("Received POST request to /process-files")
        if 'zipFile' not in request.files or 'excelFile' not in request.files:
            logger.error("Missing zipFile or excelFile in request")
            return jsonify({"error": "Missing files"}), 400

        zip_file = request.files['zipFile']
        excel_file = request.files['excelFile']

        if not zip_file.filename.lower().endswith('.zip') or \
           not excel_file.filename.lower().endswith(('.xlsx', '.xls')):
            logger.error("Invalid file format: ZIP or Excel")
            return jsonify({"error": "Invalid file format"}), 400

        UPLOAD_DIR = 'uploads'
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        paths = {
            'zip': os.path.join(UPLOAD_DIR, 'temp.zip'),
            'excel': os.path.join(UPLOAD_DIR, 'temp.xlsx'),
            'extracted': os.path.join(UPLOAD_DIR, 'extracted'),
            'output': os.path.join(UPLOAD_DIR, 'verification_results.xlsx')
        }
        
        if os.path.exists(paths['extracted']):
            shutil.rmtree(paths['extracted'])
        os.makedirs(paths['extracted'], exist_ok=True)

        zip_file.save(paths['zip'])
        excel_file.save(paths['excel'])

        with zipfile.ZipFile(paths['zip'], 'r') as z:
            z.extractall(paths['extracted'])
            logger.info(f"Extracted ZIP to {paths['extracted']}")

        df = pd.read_excel(paths['excel'])
        df['SrNo'] = df['SrNo'].astype(str).str.strip()
        df = df.fillna('')
        logger.debug(f"Loaded Excel data with columns: {df.columns.tolist()}")

        if 'SrNo' not in df.columns:
            logger.error("Excel file must have 'SrNo' column")
            return jsonify({"error": "Excel file must have 'SrNo' column"}), 400

        results, excel_data = [], []
        image_groups = {}
        for root, _, files in os.walk(paths['extracted']):
            for file in files:
                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    img_path = os.path.join(root, file)
                    serial_number = os.path.splitext(file)[0].strip()
                    base_serial_number = serial_number.split('_')[0]
                    
                    if base_serial_number not in image_groups:
                        image_groups[base_serial_number] = []
                    image_groups[base_serial_number].append((file, img_path, serial_number))
                    logger.debug(f"Image {file} mapped to base serial {base_serial_number}")

        for base_serial_number, images in image_groups.items():
            logger.info(f"Processing group for base serial: {base_serial_number}, Images: {[img[0] for img in images]}")
            
            matching_rows = df[df['SrNo'] == base_serial_number]
            if matching_rows.empty:
                for file, _, serial_number in images:
                    result = {
                        "file": file, "status": "Rejected", "document_type": "Unknown",
                        "final_remark": f"Base serial number {base_serial_number} not found in Excel"
                    }
                    results.append(result)
                    excel_data.append({**result, "SrNo": serial_number})
                logger.warning(f"No matching row found for base serial {base_serial_number}")
                continue
            
            excel_row = matching_rows.iloc[0].to_dict()
            logger.debug(f"Excel row for {base_serial_number}: {excel_row}")
            
            best_score = 0
            best_extracted = {}
            best_match_scores = {}
            best_classification = None
            processed_files = []

            for file, img_path, serial_number in images:
                classification = classify_image(img_path)
                extracted = extract_text(img_path)
                processed_files.append(file)
                
                if not extracted.get("Name"):
                    logger.error(f"Name not extracted for {file}")
                    continue
                
                score, match_scores = calculate_score(extracted, excel_row)
                if score > best_score:
                    best_score = score
                    best_extracted = extracted
                    best_match_scores = match_scores
                    best_classification = classification
            
            if best_score > 0:
                status = "Verified" if best_score >= 85 else "Rejected"
                if best_classification == "Non-Aadhaar":
                    remark = "Non Aadhaar"
                else:
                    remark = "Matched" if best_score >= 85 else "Low match score"
                
                result = {
                    "file": ", ".join(processed_files),
                    "status": status,
                    "document_type": best_classification,
                    "final_remark": f"{remark} (processed {len(processed_files)} images)" if best_classification != "Non-Aadhaar" else remark,
                    "score": round(best_score, 2)
                }
                results.append(result)
                
                excel_entry = {
                    "SrNo": base_serial_number,
                    **{f"{k}": excel_row.get(k, "") for k in [
                        "House Flat Number", "Town", "Street Road Name", "City",
                        "Country", "PINCODE", "Premise Building Name",
                        "Landmark", "State", "Name", "UID"]},
                    **{f"{k} Match Score": best_match_scores.get(f"{k} Match Score", 0)
                      for k in ["House Flat Number", "Town", "Street Road Name", "City",
                              "Country", "PINCODE", "Premise Building Name",
                              "Landmark", "State", "Name", "UID"]},
                    "Extracted Name": best_extracted.get("Name", ""),
                    "Extracted UID": best_extracted.get("UID", ""),
                    "Extracted Address": best_extracted.get("Address", ""),
                    "Overall Match": round(best_score, 2),
                    "Final Remarks": remark,
                    "Document Type": best_classification
                }
                excel_data.append(excel_entry)
                logger.info(f"Processed group {base_serial_number} with best score: {round(best_score, 2)}")
            else:
                for file, _, serial_number in images:
                    result = {
                        "file": file, "status": "Rejected", "document_type": "Unknown",
                        "final_remark": "No valid data extracted from any image"
                    }
                    results.append(result)
                    excel_data.append({**result, "SrNo": serial_number})
                logger.error(f"No valid data extracted for group {base_serial_number}")

        output_df = pd.DataFrame(excel_data)
        output_df.to_excel(paths['output'], index=False)
        logger.info(f"Saved results to {paths['output']}")

        # Send to Node.js backend
        node_data = [
            {
                "name": entry.get("Extracted Name", ""),
                "uid": entry.get("Extracted UID", ""),
                "address": entry.get("Extracted Address", ""),
                "final_remark": entry.get("Final Remarks", ""),
                "document_type": entry.get("Document Type", "")
            } for entry in excel_data
        ]
        try:
            response = requests.post(NODEJS_URL, json=node_data, timeout=10)
            response.raise_for_status()
            logger.info(f"Node.js API call successful: Status {response.status_code}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Node.js API call failed: {str(e)}")

        logger.info("Successfully processed /process-files request")
        return jsonify(results)

    except Exception as e:
        logger.error(f"Processing error: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/download-results', methods=['GET'])
def download_results():
    """Serve the verification results Excel file."""
    try:
        logger.info("Serving download-results request")
        return send_from_directory('uploads', 'verification_results.xlsx', as_attachment=True)
    except Exception as e:
        logger.error(f"Error serving file: {str(e)}")
        return jsonify({"error": "File not found"}), 404

if __name__ == '__main__':
    logger.info("Starting Flask server")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=True)