const express = require("express");
const router = express.Router();

const predictionController = require("../controllers/predictionController");

// GET AI predictions
// GET /api/predictions
router.get("/", predictionController.getPrediction);

module.exports = router;
