package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestNewStatisticsCalculator(t *testing.T) {
	calc := NewStatisticsCalculator()
	assert.NotNil(t, calc)
}

func TestStatisticsCalculator_CalculateFileStats_EmptyInput(t *testing.T) {
	calc := NewStatisticsCalculator()
	var files []*CodeFile

	stats := calc.CalculateFileStats(files)
	assert.NotNil(t, stats)

	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, stats.TotalLines)
	assert.Equal(t, 0, stats.TotalSize)
	assert.Equal(t, 0.0, stats.AverageLines)
	assert.Equal(t, 0.0, stats.AverageSize)
	assert.Equal(t, "", stats.LargestFile)
	assert.Equal(t, "", stats.SmallestFile)
	assert.NotNil(t, stats.Languages)
	assert.Len(t, stats.Languages, 0)
}

func TestStatisticsCalculator_CalculateFileStats_SingleFile(t *testing.T) {
	calc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "a.go",
			Size:     120,
			Lines:    []string{"line1", "line2", "line3"},
			Language: "Go",
		},
	}

	stats := calc.CalculateFileStats(files)
	assert.NotNil(t, stats)

	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 3, stats.TotalLines)
	assert.Equal(t, 120, stats.TotalSize)
	assert.InDelta(t, 3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 120.0, stats.AverageSize, 1e-9)
	assert.Equal(t, "a.go", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)
	assert.Equal(t, map[string]int{"Go": 1}, stats.Languages)
}

func TestStatisticsCalculator_CalculateFileStats_MultipleFiles(t *testing.T) {
	calc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "a.go",
			Size:     100,
			Lines:    []string{"l1", "l2"},
			Language: "Go",
		},
		{
			Path:     "b.py",
			Size:     200,
			Lines:    []string{"l1", "l2", "l3"},
			Language: "Python",
		},
		{
			Path:     "c.go",
			Size:     50,
			Lines:    []string{"l1", "l2", "l3", "l4"},
			Language: "Go",
		},
	}

	stats := calc.CalculateFileStats(files)
	assert.NotNil(t, stats)

	assert.Equal(t, 3, stats.TotalFiles)
	assert.Equal(t, 9, stats.TotalLines)
	assert.Equal(t, 350, stats.TotalSize)
	assert.InDelta(t, 3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, float64(350)/3.0, stats.AverageSize, 1e-9)
	assert.Equal(t, "b.py", stats.LargestFile)
	assert.Equal(t, "c.go", stats.SmallestFile)
	assert.Equal(t, map[string]int{"Go": 2, "Python": 1}, stats.Languages)
}

func TestStatisticsCalculator_CalculateFileStats_TieSizesKeepsFirst(t *testing.T) {
	calc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "first.txt",
			Size:     100,
			Lines:    []string{"a"},
			Language: "txt",
		},
		{
			Path:     "second.txt",
			Size:     100, // tie
			Lines:    []string{"b", "c"},
			Language: "txt",
		},
		{
			Path:     "third.txt",
			Size:     100, // tie
			Lines:    []string{},
			Language: "",
		},
	}

	stats := calc.CalculateFileStats(files)
	assert.NotNil(t, stats)

	// All sizes equal; since updates only on > or <, both largest and smallest should remain first file.
	assert.Equal(t, "first.txt", stats.LargestFile)
	assert.Equal(t, "first.txt", stats.SmallestFile)

	// Totals and averages
	assert.Equal(t, 3, stats.TotalFiles)
	assert.Equal(t, 3, stats.TotalLines)
	assert.Equal(t, 300, stats.TotalSize)
	assert.InDelta(t, 1.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 100.0, stats.AverageSize, 1e-9)

	// Language counts include empty string key when provided
	assert.Equal(t, 2, stats.Languages["txt"])
	assert.Equal(t, 1, stats.Languages[""])
}
