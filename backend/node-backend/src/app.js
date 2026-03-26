const express = require("express");
const cors = require("cors");

const airRoutes = require("./routes/airRoutes");
const predictionRoutes = require("./routes/predictionRoutes");
const userRoutes = require("./routes/userRoutes");

const app = express();
app.use(cors());
app.use(express.json());

app.get("/test", (req, res) => {
  res.send("API WORKING");
});

app.use("/api/air", airRoutes);
app.use("/api/predictions", predictionRoutes);
app.use("/api/users", userRoutes);

app.listen(3000, () => {
  console.log("🚀 Server running on http://localhost:3000");
});
