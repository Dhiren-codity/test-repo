package main

import (
	"log"
	"polyglot-codebase/go-service/api"

	"github.com/gin-gonic/gin"
)

func main() {
	r := gin.Default()

	handler := api.NewHandler()

	r.GET("/health", handler.HealthCheck)
	r.POST("/parse", handler.ParseFile)
	r.POST("/diff", handler.AnalyzeDiff)
	r.POST("/metrics", handler.CalculateMetrics)
	r.POST("/cache/clear", handler.ClearCache)

	log.Println("Go Parser Service starting on :8080")
	if err := r.Run(":8080"); err != nil {
		log.Fatal("Failed to start server:", err)
	}
}
