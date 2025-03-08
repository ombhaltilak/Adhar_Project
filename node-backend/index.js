const express = require('express');
const { MongoClient } = require('mongodb');
const dotenv = require('dotenv');
const path = require('path');
const fs = require('fs');
const ExcelJS = require('exceljs'); // For generating Excel files

dotenv.config();

const app = express();
const port = process.env.PORT || 3000;
const mongoUri = process.env.MONGODB_URI;
console.log('MongoDB URI:', mongoUri);

app.use(express.json());

// MongoDB Client
let db;
let client;

async function connectToMongo() {
    try {
        if (!mongoUri) {
            throw new Error('MONGODB_URI is not defined in .env');
        }
        client = new MongoClient(mongoUri);
        await client.connect();
        console.log('Connected to MongoDB Atlas');

        const parsedUri = new URL(mongoUri);
        const dbName = parsedUri.pathname.replace('/', '') || 'verification_db';
        db = client.db(dbName);
        console.log(`Using database: ${dbName}`);
    } catch (error) {
        console.error('MongoDB connection error:', error);
        process.exit(1);
    }
}

// Define the expected data structure (pseudo-schema)
const verificationSchema = {
    name: String,
    uid: String,
    address: String,
    final_remark: String,
    document_type: String
};

// Store verification results from Flask with specific fields
app.post('/store-results', async (req, res) => {
    try {
        if (!db) {
            return res.status(500).json({ error: 'Database not connected' });
        }

        const results = req.body;
        if (!Array.isArray(results) || results.length === 0) {
            return res.status(400).json({ error: 'Invalid or empty results' });
        }

        // Log incoming data for debugging
        console.log('Received data:', results);

        // Validate and format results
        const formattedResults = results.map(result => {
            if (typeof result !== 'object' || result === null) {
                throw new Error('Invalid result object');
            }
            return {
                name: result['name'] || '',
                uid: result['uid'] || '',
                address: result['address'] || '',
                final_remark: result['final_remark'] || '',
                document_type: result['document_type'] || '',
                timestamp: new Date() // Add timestamp for tracking
            };
        });

        const collection = db.collection('verification_results');
        const insertResult = await collection.insertMany(formattedResults);
        
        res.status(201).json({
            message: 'Results stored successfully',
            insertedCount: insertResult.insertedCount
        });
    } catch (error) {
        console.error('Error storing results:', error);
        res.status(500).json({ error: 'Failed to store results', details: error.message });
    }
});

// Retrieve all stored results
app.get('/get-results', async (req, res) => {
    try {
        if (!db) {
            return res.status(500).json({ error: 'Database not connected' });
        }

        const collection = db.collection('verification_results');
        const results = await collection.find({}).toArray();
        
        res.status(200).json(results);
    } catch (error) {
        console.error('Error retrieving results:', error);
        res.status(500).json({ error: 'Failed to retrieve results', details: error.message });
    }
});

// Generate and serve Excel file
app.get('/download-results', async (req, res) => {
    try {
        if (!db) {
            return res.status(500).json({ error: 'Database not connected' });
        }

        const collection = db.collection('verification_results');
        const results = await collection.find({}).toArray();

        if (!results || results.length === 0) {
            return res.status(404).json({ error: 'No results found to export' });
        }

        // Create a new workbook and worksheet
        const workbook = new ExcelJS.Workbook();
        const worksheet = workbook.addWorksheet('Verification Results');

        // Define columns
        worksheet.columns = [
            { header: 'Name', key: 'name', width: 20 },
            { header: 'UID', key: 'uid', width: 15 },
            { header: 'Address', key: 'address', width: 30 },
            { header: 'Final Remark', key: 'final_remark', width: 25 },
            { header: 'Document Type', key: 'document_type', width: 20 },
            { header: 'Timestamp', key: 'timestamp', width: 20 }
        ];

        // Add data rows
        worksheet.addRows(results);

        // Generate the Excel file
        const filePath = path.join(__dirname, '../uploads', 'verification_results.xlsx');
        const uploadDir = path.dirname(filePath);
        if (!fs.existsSync(uploadDir)) {
            fs.mkdirSync(uploadDir, { recursive: true });
        }

        await workbook.xlsx.writeFile(filePath);
        res.download(filePath, 'verification_results.xlsx', (err) => {
            if (err) {
                console.error('Error downloading file:', err);
                res.status(500).json({ error: 'Failed to download file' });
            } else {
                // Optionally clean up the file after download
                fs.unlink(filePath, (err) => {
                    if (err) console.error('Error deleting file:', err);
                });
            }
        });
    } catch (error) {
        console.error('Error generating or downloading file:', error);
        res.status(500).json({ error: 'Failed to generate or download file', details: error.message });
    }
});

// Graceful shutdown
process.on('SIGTERM', async () => {
    console.log('SIGTERM received, shutting down gracefully...');
    if (client) {
        await client.close();
        console.log('MongoDB connection closed');
    }
    process.exit(0);
});

process.on('SIGINT', async () => {
    console.log('SIGINT received, shutting down gracefully...');
    if (client) {
        await client.close();
        console.log('MongoDB connection closed');
    }
    process.exit(0);
});

// Start the server
async function startServer() {
    await connectToMongo();
    app.listen(port, () => {
        console.log(`Node.js server running on port ${port}`);
    });
}

startServer().catch(err => {
    console.error('Server startup failed:', err);
    process.exit(1);
});