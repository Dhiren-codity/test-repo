package main

import (
	"log"
	"net/http"
	"polyglot-codebase/go-service/api"
	"polyglot-codebase/go-service/middleware"

	"github.com/gin-gonic/gin"
)

func main() {
	r := gin.Default()

	r.Use(correlationIDMiddleware())
	r.Use(validationMiddleware())

	handler := api.NewHandler()

	r.GET("/health", handler.HealthCheck)
	r.POST("/parse", handler.ParseFile)
	r.POST("/diff", handler.AnalyzeDiff)
	r.POST("/metrics", handler.CalculateMetrics)
	r.POST("/statistics", handler.GetStatistics)

	r.GET("/traces", func(c *gin.Context) {
		traces := middleware.GetAllTraces()
		c.JSON(http.StatusOK, gin.H{
			"total_traces": len(traces),
			"traces":       traces,
		})
	})

	r.GET("/traces/:correlation_id", func(c *gin.Context) {
		correlationID := c.Param("correlation_id")
		traces := middleware.GetTraces(correlationID)

		if len(traces) == 0 {
			c.JSON(http.StatusNotFound, gin.H{"error": "No traces found for correlation ID"})
			return
		}

		c.JSON(http.StatusOK, gin.H{
			"correlation_id": correlationID,
			"trace_count":    len(traces),
			"traces":         traces,
		})
	})

	r.GET("/validation/errors", func(c *gin.Context) {
		errors := middleware.GetValidationErrors()
		c.JSON(http.StatusOK, gin.H{
			"total_errors": len(errors),
			"errors":       errors,
		})
	})

	r.DELETE("/validation/errors", func(c *gin.Context) {
		middleware.ClearValidationErrors()
		c.JSON(http.StatusOK, gin.H{"message": "Validation errors cleared"})
	})

	log.Println("Go Parser Service starting on :8080")
	if err := r.Run(":8080"); err != nil {
		log.Fatal("Failed to start server:", err)
	}
}

func correlationIDMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		correlationID := middleware.ExtractOrGenerateID(c.Request)
		c.Request.Header.Set(middleware.CorrelationIDHeader, correlationID)
		c.Writer.Header().Set(middleware.CorrelationIDHeader, correlationID)

		middleware.TrackRequest(c.Request, c.Writer.Status())

		c.Next()
	}
}

func validationMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		if c.Request.Method == http.MethodPost {
			middleware.SanitizeRequestBody(c.Request)
		}
		c.Next()
	}
}
