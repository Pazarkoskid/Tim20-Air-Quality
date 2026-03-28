const db = require("../database/db");
const bcrypt = require("bcrypt");
const User = require("../models/User");

exports.createUser = async (name, email, password) => {
    return new Promise((resolve, reject) => {
        db.get("SELECT * FROM Users WHERE email = ?", [email], async (err, user) => {
            if (err) return reject(err);
            if (user) return reject("User already exists");

            const hashed = await bcrypt.hash(password, 10);

            db.run(
                `INSERT INTO Users (name, email, password) VALUES (?, ?, ?)`,
                [name, email, hashed],
                function (err) {
                    if (err) return reject(err);

                    resolve(new User(this.lastID, name, email));
                }
            );
        });
    });
};