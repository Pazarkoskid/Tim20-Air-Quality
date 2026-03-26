const express = require("express");
const router = express.Router();

const airController = require("../controllers/airController");

// GET current air quality
// GET /api/air
router.get("/", airController.getAir);

module.exports = router;
