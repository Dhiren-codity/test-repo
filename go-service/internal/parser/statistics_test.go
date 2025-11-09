package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func makeLines(n int) []string {
	lines := make([]string, n)
	for i := 0; i < n; i++ {
		lines[i] = "line"
	}
	return lines
}

func TestNewStatisticsCalculator_ReturnsNonNil(t *testing.T) {
	calc := NewStatisticsCalculator()
	assert.NotNil(t, calc)
}

func TestCalculateFileStats_EmptyInput(t *testing.T) {
	calc := NewStatisticsCalculator()

	stats := calc.CalculateFileStats([]*CodeFile{})
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

func TestCalculateFileStats_NilSliceInput(t *testing.T) {
	calc := NewStatisticsCalculator()

	var files []*CodeFile // nil slice
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

func TestCalculateFileStats_SingleFile(t *testing.T) {
	calc := NewStatisticsCalculator()

	file := &CodeFile{
		Path:     "a.go",
		Language: "go",
		Lines:    makeLines(10),
		Size:     123,
	}

	stats := calc.CalculateFileStats([]*CodeFile{file})
	assert.NotNil(t, stats)

	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 10, stats.TotalLines)
	assert.Equal(t, 123, stats.TotalSize)
	assert.InDelta(t, 10.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 123.0, stats.AverageSize, 1e-9)
	assert.Equal(t, "a.go", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)
	assert.Equal(t, 1, stats.Languages["go"])
}

func TestCalculateFileStats_MultipleFilesCountsAndExtremes(t *testing.T) {
	calc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "a.go",
			Language: "go",
			Lines:    makeLines(10),
			Size:     100,
		},
		{
			Path:     "b.js",
			Language: "js",
			Lines:    makeLines(20),
			Size:     200,
		},
		{
			Path:     "c.go",
			Language: "go",
			Lines:    makeLines(5),
			Size:     50,
		},
	}

	stats := calc.CalculateFileStats(files)
	assert.NotNil(t, stats)

	assert.Equal(t, 3, stats.TotalFiles)
	assert.Equal(t, 35, stats.TotalLines)
	assert.Equal(t, 350, stats.TotalSize)
	assert.InDelta(t, float64(35)/3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, float64(350)/3.0, stats.AverageSize, 1e-9)

	assert.Equal(t, "b.js", stats.LargestFile)
	assert.Equal(t, "c.go", stats.SmallestFile)

	assert.Equal(t, 2, stats.Languages["go"])
	assert.Equal(t, 1, stats.Languages["js"])
}

func TestCalculateFileStats_LargestFileTieKeepsFirst(t *testing.T) {
	calc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "f1.txt",
			Language: "txt",
			Lines:    makeLines(1),
			Size:     100,
		},
		{
			Path:     "f2.txt",
			Language: "txt",
			Lines:    makeLines(2),
			Size:     200,
		},
		{
			Path:     "f3.txt",
			Language: "txt",
			Lines:    makeLines(3),
			Size:     200, // tie with f2; should not replace f2
		},
	}

	stats := calc.CalculateFileStats(files)
	assert.NotNil(t, stats)
	assert.Equal(t, "f2.txt", stats.LargestFile)
}

func TestCalculateFileStats_SmallestFileTieKeepsFirst(t *testing.T) {
	calc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "f1.txt",
			Language: "txt",
			Lines:    makeLines(1),
			Size:     100,
		},
		{
			Path:     "f2.txt",
			Language: "txt",
			Lines:    makeLines(2),
			Size:     50,
		},
		{
			Path:     "f3.txt",
			Language: "txt",
			Lines:    makeLines(3),
			Size:     50, // tie with f2; should not replace f2
		},
	}

	stats := calc.CalculateFileStats(files)
	assert.NotNil(t, stats)
	assert.Equal(t, "f2.txt", stats.SmallestFile)
}
