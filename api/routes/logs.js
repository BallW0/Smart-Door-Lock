'use strict';

const express = require('express');
const router  = express.Router();
const { db }  = require('../server');

// ── GET / ─────────────────────────────────────────────────────
// Retrieve access logs.
// Query param: ?limit=50 (default 50, max enforced by caller)
// Returns an array sorted descending by timestamp (newest first).
router.get('/', async (req, res) => {
  try {
    const limit = parseInt(req.query.limit, 10) || 50;

    // Order by timestamp, take the last N (most recent)
    const snapshot = await db.ref('access_logs')
      .orderByChild('timestamp')
      .limitToLast(limit)
      .once('value');

    const raw = snapshot.val();

    if (!raw) {
      return res.status(200).json([]);
    }

    // Convert Firebase object → array, then sort descending (newest first)
    const logs = Object.entries(raw)
      .map(([id, val]) => ({ id, ...val }))
      .sort((a, b) => (b.timestamp > a.timestamp ? 1 : -1));

    return res.status(200).json(logs);
  } catch (err) {
    console.error('[Logs] GET / error:', err.message);
    return res.status(500).json({ error: 'Failed to fetch logs', message: err.message });
  }
});

// ── POST / ────────────────────────────────────────────────────
// Add a new access log entry.
// Body: { method: string, status: 'granted'|'denied', user: string, details?: string }
//
// Side-effects:
//   - Updates system/last_activity
//   - If status === 'granted'  → sets system/door_status = 'unlocked'
//   - If status !== 'granted'  → leaves door_status as 'locked'
router.post('/', async (req, res) => {
  try {
    const { method, status, user, details } = req.body;

    if (!method || !status || !user) {
      return res.status(400).json({ error: 'method, status, and user are required' });
    }

    const timestamp = new Date().toISOString();

    const logEntry = {
      timestamp,
      method,
      status,
      user,
      details: details || '',
    };

    // Push new log entry with auto-generated key
    const logRef = db.ref('access_logs').push();
    await logRef.set(logEntry);

    // Build system updates
    const systemUpdates = {
      'system/last_activity': timestamp,
    };
    if (status === 'granted') {
      systemUpdates['system/door_status'] = 'unlocked';
    } else {
      systemUpdates['system/door_status'] = 'locked';
    }

    await db.ref().update(systemUpdates);

    return res.status(201).json({ id: logRef.key, ...logEntry });
  } catch (err) {
    console.error('[Logs] POST / error:', err.message);
    return res.status(500).json({ error: 'Failed to add log entry', message: err.message });
  }
});

// ── DELETE /clear ─────────────────────────────────────────────
// Remove ALL log entries from Firebase access_logs node.
// Use with caution — this is irreversible.
router.delete('/clear', async (req, res) => {
  try {
    await db.ref('access_logs').remove();

    return res.status(200).json({ success: true, message: 'All access logs cleared' });
  } catch (err) {
    console.error('[Logs] DELETE /clear error:', err.message);
    return res.status(500).json({ error: 'Failed to clear logs', message: err.message });
  }
});

module.exports = router;
