const express = require("express");
const router = express.Router();

const predictionController = require("../controllers/predictionController");

/**
 * @swagger
 * /api/predictions:
 *   get:
 *     summary: Get AI prediction for air quality
 *     tags: [Predictions]
 *     responses:
 *       200:
 *         description: Prediction returned successfully
 */
router.get("/", predictionController.getPrediction);

module.exports = router;