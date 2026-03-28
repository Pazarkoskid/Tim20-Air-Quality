const db = require("../database/db");
const bcrypt = require("bcrypt");
const jwt = require("jsonwebtoken");
const User = require("../models/User");

const SECRET = "mysecretkey"; // подоцна може .env

exports.loginUser = (email, password) => {
    return new Promise((resolve, reject) => {
        db.get(
            "SELECT * FROM Users WHERE email = ?",
            [email],
            async (err, user) => {
                if (err) return reject(err);
                if (!user) return reject("User not found");

                const isMatch = await bcrypt.compare(password, user.password);
                if (!isMatch) return reject("Invalid password");

                const token = jwt.sign(
                    { id: user.id, email: user.email },
                    SECRET,
                    { expiresIn: "1h" }
                );

                resolve({
                    token,
                    user: new User(user.id, user.name, user.email),
                });
            }
        );
    });
};