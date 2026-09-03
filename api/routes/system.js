'use strict';

const express = require('express');
const router  = express.Router();
const { db }  = require('../server');

router.get('/status', async (req, res) => {
  try {
    const snapshot = await db.ref('system').once('value');
    const data     = snapshot.val() || {};

    return res.status(200).json({
      door_status:               data.door_status               || 'locked',
      face_recognized:           data.face_recognized           || false,
      face_recognition_timestamp: data.face_recognition_timestamp || null,
      last_activity:             data.last_activity             || null,
      pending_command:           data.pending_command           || null,
    });
  } catch (err) {
    console.error('[System] GET /status error:', err.message);
    return res.status(500).json({ error: 'Failed to fetch system status', message: err.message });
  }
});

// ── POST /face-recognized ─────────────────────────────────────
// Called by ESP32-CAM or a Python face-recognition process when
// a face detection event occurs.
// Body: { recognized: true|false }
//
// Writes:
//   system/face_recognized           = true  (always true when this endpoint is hit)
//   system/face_recognition_timestamp = Date.now() (Unix ms)
router.post('/face-recognized', async (req, res) => {
  try {
    const { recognized } = req.body;

    if (recognized === undefined || recognized === null) {
      return res.status(400).json({ error: 'recognized field is required' });
    }

    const timestamp = Date.now();

    await db.ref('system').update({
      face_recognized:            recognized === true || recognized === 'true',
      face_recognition_timestamp: timestamp,
    });

    return res.status(200).json({
      success:                    true,
      face_recognized:            recognized === true || recognized === 'true',
      face_recognition_timestamp: timestamp,
    });
  } catch (err) {
    console.error('[System] POST /face-recognized error:', err.message);
    return res.status(500).json({ error: 'Failed to update face recognition status', message: err.message });
  }
});

// ── POST /clear-face-recognized ───────────────────────────────
// Clears the face_recognized flag so DevKit doesn't trigger repeatedly
router.post('/clear-face-recognized', async (req, res) => {
  try {
    await db.ref('system').update({ face_recognized: false });
    return res.status(200).json({ success: true, message: 'Face flag cleared' });
  } catch (err) {
    console.error('[System] POST /clear-face-recognized error:', err.message);
    return res.status(500).json({ error: 'Failed to clear face flag', message: err.message });
  }
});

// ── GET /pending-command ──────────────────────────────────────
// Called by ESP32 DevKit to poll for a pending command.
// If a command is present, returns it; otherwise returns null.
//
// Returns: { command: null } | { command: { type, slot, name, issued_at } }
router.get('/pending-command', async (req, res) => {
  try {
    const snapshot = await db.ref('system/pending_command').once('value');
    const command  = snapshot.val();

    return res.status(200).json({ command: command || null });
  } catch (err) {
    console.error('[System] GET /pending-command error:', err.message);
    return res.status(500).json({ error: 'Failed to fetch pending command', message: err.message });
  }
});

// ── POST /clear-command ───────────────────────────────────────
// Called by ESP32 DevKit after it has executed the pending command.
// Clears system/pending_command by setting it to null.
router.post('/clear-command', async (req, res) => {
  try {
    await db.ref('system/pending_command').set(null);

    return res.status(200).json({ success: true, message: 'Pending command cleared' });
  } catch (err) {
    console.error('[System] POST /clear-command error:', err.message);
    return res.status(500).json({ error: 'Failed to clear pending command', message: err.message });
  }
});

// ── POST /door-status ─────────────────────────────────────────
// Update the door lock status.
// Body: { status: 'locked' | 'unlocked' }
router.post('/door-status', async (req, res) => {
  try {
    const { status } = req.body;

    if (!status) {
      return res.status(400).json({ error: 'status is required' });
    }

    if (status !== 'locked' && status !== 'unlocked') {
      return res.status(400).json({
        error: 'Invalid status value. Must be "locked" or "unlocked"',
      });
    }

    await db.ref('system').update({ door_status: status });

    return res.status(200).json({ success: true, door_status: status });
  } catch (err) {
    console.error('[System] POST /door-status error:', err.message);
    return res.status(500).json({ error: 'Failed to update door status', message: err.message });
  }
});

module.exports = router;
