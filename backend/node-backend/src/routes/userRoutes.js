const express = require("express");
const router = express.Router();

const userController = require("../controllers/userController");

// REGISTER USER
// POST /api/users/register
router.post("/register", userController.register);

module.exports = router;
