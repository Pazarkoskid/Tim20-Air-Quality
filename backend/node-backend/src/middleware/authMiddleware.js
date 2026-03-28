const jwt = require("jsonwebtoken");

const SECRET = "mysecretkey";

module.exports = (req, res, next) => {
    const authHeader = req.headers.authorization;

    if (!authHeader) {
        return res.status(401).json("No token provided");
    }

    const token = authHeader.split(" ")[1];

    try {
        const decoded = jwt.verify(token, SECRET);
        req.user = decoded;
        next();
    } catch (err) {
        res.status(401).json("Invalid token");
    }
};