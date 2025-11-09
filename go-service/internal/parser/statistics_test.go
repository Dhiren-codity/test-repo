package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestNewStatisticsCalculator(t *testing.T) {
	calc := NewStatisticsCalculator()
	assert.NotNil(t, calc)
}

func TestStatisticsCalculator_CalculateFileStats_Empty(t *testing.T) {
	calc := NewStatisticsCalculator()
	stats := calc.CalculateFileStats(nil)

	assert.NotNil(t, stats)
	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, stats.TotalLines)
	assert.Equal(t, 0, stats.TotalSize)
	assert.NotNil(t, stats.Languages)
	assert.Len(t, stats.Languages, 0)
	assert.Equal(t, 0.0, stats.AverageLines)
	assert.Equal(t, 0.0, stats.AverageSize)
	assert.Equal(t, "", stats.LargestFile)
	assert.Equal(t, "", stats.SmallestFile)
}

func TestStatisticsCalculator_CalculateFileStats_SingleFile(t *testing.T) {
	calc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "a.go",
			Lines:    []string{"package main", "func main() {}", "// end"},
			Size:     100,
			Language: "Go",
		},
	}

	stats := calc.CalculateFileStats(files)

	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 3, stats.TotalLines)
	assert.Equal(t, 100, stats.TotalSize)

	assert.NotNil(t, stats.Languages)
	assert.Equal(t, 1, stats.Languages["Go"])

	assert.InDelta(t, 3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 100.0, stats.AverageSize, 1e-9)

	assert.Equal(t, "a.go", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)
}

func TestStatisticsCalculator_CalculateFileStats_MultipleFiles(t *testing.T) {
	calc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "a.go",
			Lines:    []string{"l1", "l2"},
			Size:     10,
			Language: "Go",
		},
		{
			Path:     "b.py",
			Lines:    []string{"l1", "l2", "l3"},
			Size:     30,
			Language: "Python",
		},
		{
			Path:     "c.go",
			Lines:    []string{"l1"},
			Size:     20,
			Language: "Go",
		},
	}

	stats := calc.CalculateFileStats(files)

	assert.Equal(t, 3, stats.TotalFiles)
	assert.Equal(t, 6, stats.TotalLines)
	assert.Equal(t, 60, stats.TotalSize)

	// Language counts
	assert.NotNil(t, stats.Languages)
	assert.Equal(t, 2, stats.Languages["Go"])
	assert.Equal(t, 1, stats.Languages["Python"])

	// Averages
	assert.InDelta(t, 2.0, stats.AverageLines, 1e-9) // 6 / 3
	assert.InDelta(t, 20.0, stats.AverageSize, 1e-9) // 60 / 3

	// Largest/smallest
	assert.Equal(t, "b.py", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)
}

func TestStatisticsCalculator_CalculateFileStats_SizeTiesKeepFirst(t *testing.T) {
	calc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "a.txt",
			Lines:    []string{"a"},
			Size:     10,
			Language: "Text",
		},
		{
			Path:     "b.txt",
			Lines:    []string{"b1", "b2"},
			Size:     10, // tie with a.txt
			Language: "Text",
		},
	}

	stats := calc.CalculateFileStats(files)

	assert.Equal(t, 2, stats.TotalFiles)
	assert.Equal(t, 3, stats.TotalLines)
	assert.Equal(t, 20, stats.TotalSize)

	assert.Equal(t, "a.txt", stats.LargestFile)  // tie should keep first
	assert.Equal(t, "a.txt", stats.SmallestFile) // tie should keep first

	assert.InDelta(t, 1.5, stats.AverageLines, 1e-9)
	assert.InDelta(t, 10.0, stats.AverageSize, 1e-9)
}
