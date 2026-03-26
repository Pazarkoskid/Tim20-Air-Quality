const db = require("../database/db");
const bcrypt = require("bcrypt");

exports.register = async (req, res) => {
  const { name, email, password } = req.body;

  const hashed = await bcrypt.hash(password, 10);

  db.run(
    `INSERT INTO Users (name, email, password)
     VALUES (?, ?, ?)`,
    [name, email, hashed],
    function (err) {
      if (err) return res.status(500).json(err.message);

      res.json({
        id: this.lastID,
        name,
        email,
      });
    },
  );
};
