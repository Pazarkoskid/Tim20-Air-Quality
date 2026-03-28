const userService = require("../services/userService");

exports.register = async (req, res) => {
    try {
        const { name, email, password } = req.body;

        if (!name || !email || !password) {
            return res.status(400).json("All fields are required");
        }

        const user = await userService.createUser(name, email, password);

        res.status(201).json(user);
    } catch (err) {
        res.status(500).json(err);
    }
};