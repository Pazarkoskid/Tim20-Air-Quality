const authService = require("../services/authService");

exports.login = async (req, res) => {
    try {
        const { email, password } = req.body;

        if (!email || !password) {
            return res.status(400).json("Email and password required");
        }

        const result = await authService.loginUser(email, password);

        res.json(result);
    } catch (err) {
        res.status(401).json(err);
    }
};