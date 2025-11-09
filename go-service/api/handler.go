package api

import (
	"net/http"
	"polyglot-codebase/go-service/internal/parser"

	"github.com/gin-gonic/gin"
)

type Handler struct {
	parser *parser.Parser
}

func NewHandler() *Handler {
	return &Handler{
		parser: parser.NewParser(),
	}
}

type ParseRequest struct {
	Content string `json:"content" binding:"required"`
	Path    string `json:"path" binding:"required"`
}

type DiffRequest struct {
	OldContent string `json:"old_content" binding:"required"`
	NewContent string `json:"new_content" binding:"required"`
}

type MetricsRequest struct {
	Content string `json:"content" binding:"required"`
}

func (h *Handler) ParseFile(c *gin.Context) {
	var req ParseRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	file, err := h.parser.ParseFile(req.Content, req.Path)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, file)
}

func (h *Handler) AnalyzeDiff(c *gin.Context) {
	var req DiffRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	diff, err := h.parser.AnalyzeDiff(req.OldContent, req.NewContent)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, diff)
}

func (h *Handler) CalculateMetrics(c *gin.Context) {
	var req MetricsRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	metrics := h.parser.CalculateMetrics(req.Content)
	c.JSON(http.StatusOK, metrics)
}

func (h *Handler) HealthCheck(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":  "healthy",
		"service": "go-parser",
	})
}
