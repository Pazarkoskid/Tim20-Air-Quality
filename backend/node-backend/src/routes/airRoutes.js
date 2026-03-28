const express = require("express");
const router = express.Router();
const authMiddleware = require("../middleware/authMiddleware");

const airController = require("../controllers/airController");

/**
 * @swagger
 * /api/air:
 *   get:
 *     summary: Get current air quality data
 *     tags: [Air]
 *     responses:
 *       200:
 *         description: Air quality data returned successfully
 */
router.get("/", authMiddleware, airController.getAir);

module.exports = router;