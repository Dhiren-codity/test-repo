package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestNewStatisticsCalculator_NotNil(t *testing.T) {
	sc := NewStatisticsCalculator()
	assert.NotNil(t, sc)
}

func TestCalculateFileStats_EmptyInput(t *testing.T) {
	sc := NewStatisticsCalculator()
	stats := sc.CalculateFileStats(nil)

	assert.NotNil(t, stats)
	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, stats.TotalLines)
	assert.Equal(t, 0, stats.TotalSize)
	assert.NotNil(t, stats.Languages)
	assert.Equal(t, 0, len(stats.Languages))
	assert.Equal(t, 0.0, stats.AverageLines)
	assert.Equal(t, 0.0, stats.AverageSize)
	assert.Equal(t, "", stats.LargestFile)
	assert.Equal(t, "", stats.SmallestFile)
}

func TestCalculateFileStats_SingleFile(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "a.go",
			Size:     10,
			Language: "Go",
			Lines:    make([]string, 2),
		},
	}

	stats := sc.CalculateFileStats(files)

	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 2, stats.TotalLines)
	assert.Equal(t, 10, stats.TotalSize)
	assert.Equal(t, 2.0, stats.AverageLines)
	assert.Equal(t, 10.0, stats.AverageSize)
	assert.Equal(t, "a.go", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)

	assert.Len(t, stats.Languages, 1)
	assert.Equal(t, 1, stats.Languages["Go"])
}

func TestCalculateFileStats_MultipleFiles_AggregatesAndAverages_LargestSmallest_Ties(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "f1",
			Size:     100,
			Language: "Go",
			Lines:    make([]string, 3),
		},
		{
			Path:     "f2",
			Size:     50,
			Language: "Go",
			Lines:    make([]string, 2),
		},
		{
			Path:     "f3",
			Size:     150,
			Language: "Python",
			Lines:    make([]string, 1),
		},
		{
			Path:     "f4",
			Size:     150, // tie with f3; largest should remain "f3" because only > updates
			Language: "",
			Lines:    make([]string, 4),
		},
	}

	stats := sc.CalculateFileStats(files)

	assert.Equal(t, 4, stats.TotalFiles)
	assert.Equal(t, 10, stats.TotalLines) // 3+2+1+4
	assert.Equal(t, 450, stats.TotalSize) // 100+50+150+150
	assert.InDelta(t, 2.5, stats.AverageLines, 1e-9)
	assert.InDelta(t, 112.5, stats.AverageSize, 1e-9)

	assert.Equal(t, "f3", stats.LargestFile)
	assert.Equal(t, "f2", stats.SmallestFile)

	// Language counts
	assert.Equal(t, 2, stats.Languages["Go"])
	assert.Equal(t, 1, stats.Languages["Python"])
	assert.Equal(t, 1, stats.Languages[""])
}

func TestCalculateFileStats_TieSizes_KeepFirstForLargestAndSmallest(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "first",
			Size:     10,
			Language: "X",
			Lines:    make([]string, 1),
		},
		{
			Path:     "second",
			Size:     10, // equal size; shouldn't replace largest/smallest
			Language: "Y",
			Lines:    make([]string, 2),
		},
	}

	stats := sc.CalculateFileStats(files)

	assert.Equal(t, "first", stats.LargestFile)
	assert.Equal(t, "first", stats.SmallestFile)
}
