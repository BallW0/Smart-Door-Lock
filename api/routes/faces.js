const express = require('express');
const router = express.Router();
const fs = require('fs');
const path = require('path');

const KNOWN_FACES_DIR = path.join(__dirname, '../../python-face-recognition/known_faces');
const MODEL_FILE = path.join(KNOWN_FACES_DIR, 'trained_model.yml');
const LABEL_MAP_FILE = path.join(KNOWN_FACES_DIR, 'label_map.json');

// POST /api/faces/register
router.post('/register', (req, res) => {
  try {
    const { name, images } = req.body;
    
    if (!name || !images || !Array.isArray(images) || images.length === 0) {
      return res.status(400).json({ error: 'Missing name or images array' });
    }

    // Sanitize directory name
    const safeName = name.replace(/[^a-z0-9]/gi, '_').toLowerCase();
    const personDir = path.join(KNOWN_FACES_DIR, safeName);

    // Create directory for the person if it doesn't exist
    if (!fs.existsSync(personDir)) {
      fs.mkdirSync(personDir, { recursive: true });
    } else {
      // If updating, you might want to clear old images or just overwrite
      // Here we will just write new ones and let python handle it.
    }

    // Write images
    images.forEach((base64String, index) => {
      // Remove data URL prefix if present
      const base64Data = base64String.replace(/^data:image\/\w+;base64,/, '');
      const buffer = Buffer.from(base64Data, 'base64');
      
      const fileName = `face_${index.toString().padStart(3, '0')}.jpg`;
      fs.writeFileSync(path.join(personDir, fileName), buffer);
    });

    console.log(`[Face API] Saved ${images.length} images for ${safeName}`);

    // Delete trained_model.yml and label_map.json to force Python to retrain
    if (fs.existsSync(MODEL_FILE)) {
      fs.unlinkSync(MODEL_FILE);
      console.log(`[Face API] Deleted ${MODEL_FILE} to trigger retraining`);
    }
    if (fs.existsSync(LABEL_MAP_FILE)) {
      fs.unlinkSync(LABEL_MAP_FILE);
      console.log(`[Face API] Deleted ${LABEL_MAP_FILE}`);
    }

    res.json({ success: true, message: `Successfully registered face for ${name}` });

  } catch (error) {
    console.error('[Face API] Error:', error);
    res.status(500).json({ error: 'Internal server error', details: error.message });
  }
});

module.exports = router;
