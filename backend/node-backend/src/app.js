const express = require("express");
const cors = require("cors");

const airRoutes = require("./routes/airRoutes");
const predictionRoutes = require("./routes/predictionRoutes");
const userRoutes = require("./routes/userRoutes");

const swaggerUi = require("swagger-ui-express");
const swaggerJsdoc = require("swagger-jsdoc");
const authRoutes = require("./routes/authRoutes");

const app = express();

// Middleware
app.use(cors());
app.use(express.json());

// Swagger config
const options = {
    definition: {
        openapi: "3.0.0",
        info: {
            title: "Air Quality API",
            version: "1.0.0",
        },
        components: {
            securitySchemes: {
                bearerAuth: {
                    type: "http",
                    scheme: "bearer",
                    bearerFormat: "JWT",
                },
            },
        },
        security: [
            {
                bearerAuth: [],
            },
        ],


    },

    apis: ["./src/routes/*.js"], // ⚠️ важно за твојата структура
};

const specs = swaggerJsdoc(options);

// Swagger route
app.use("/api-docs", swaggerUi.serve, swaggerUi.setup(specs));

// Test route
app.get("/test", (req, res) => {
    res.send("API WORKING");
});

// API routes
app.use("/api/air", airRoutes);
app.use("/api/predictions", predictionRoutes);
app.use("/api/users", userRoutes);
app.use("/api/auth", authRoutes);

// Start server
app.listen(3000, () => {
    console.log("🚀 Server running on http://localhost:3000");
});