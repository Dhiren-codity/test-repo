package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestNewStatisticsCalculator_ReturnsNonNil(t *testing.T) {
	sc := NewStatisticsCalculator()
	require.NotNil(t, sc)
}

func buildLines(n int) []string {
	lines := make([]string, n)
	for i := 0; i < n; i++ {
		lines[i] = "line"
	}
	return lines
}

func newCodeFile(path string, size int, lines int, lang string) *CodeFile {
	return &CodeFile{
		Path:     path,
		Size:     size,
		Lines:    buildLines(lines),
		Language: lang,
	}
}

func TestStatisticsCalculator_CalculateFileStats(t *testing.T) {
	sc := NewStatisticsCalculator()
	require.NotNil(t, sc)

	tests := []struct {
		name             string
		files            []*CodeFile
		wantTotalFiles   int
		wantTotalLines   int
		wantTotalSize    int
		wantLargestFile  string
		wantSmallestFile string
		wantLanguages    map[string]int
	}{
		{
			name:           "nil slice",
			files:          nil,
			wantTotalFiles: 0,
			wantLanguages:  map[string]int{},
		},
		{
			name:           "empty slice",
			files:          []*CodeFile{},
			wantTotalFiles: 0,
			wantLanguages:  map[string]int{},
		},
		{
			name: "single file",
			files: []*CodeFile{
				newCodeFile("/a.go", 100, 10, "Go"),
			},
			wantTotalFiles:   1,
			wantTotalLines:   10,
			wantTotalSize:    100,
			wantLargestFile:  "/a.go",
			wantSmallestFile: "/a.go",
			wantLanguages:    map[string]int{"Go": 1},
		},
		{
			name: "multiple files aggregates correctly",
			files: []*CodeFile{
				newCodeFile("/a.go", 100, 10, "Go"),
				newCodeFile("/b.py", 50, 5, "Python"),
				newCodeFile("/c.go", 200, 20, "Go"),
			},
			wantTotalFiles:   3,
			wantTotalLines:   35,
			wantTotalSize:    350,
			wantLargestFile:  "/c.go",
			wantSmallestFile: "/b.py",
			wantLanguages:    map[string]int{"Go": 2, "Python": 1},
		},
		{
			name: "tie sizes keeps first for largest and smallest",
			files: []*CodeFile{
				newCodeFile("/a", 100, 1, "X"),
				newCodeFile("/b", 100, 2, "Y"),
			},
			wantTotalFiles:   2,
			wantTotalLines:   3,
			wantTotalSize:    200,
			wantLargestFile:  "/a",
			wantSmallestFile: "/a",
			wantLanguages:    map[string]int{"X": 1, "Y": 1},
		},
		{
			name: "zero-size file included",
			files: []*CodeFile{
				newCodeFile("/zero", 0, 0, "Text"),
				newCodeFile("/nonzero", 42, 3, "Text"),
			},
			wantTotalFiles:   2,
			wantTotalLines:   3,
			wantTotalSize:    42,
			wantLargestFile:  "/nonzero",
			wantSmallestFile: "/zero",
			wantLanguages:    map[string]int{"Text": 2},
		},
	}

	const floatDelta = 1e-9

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			stats := sc.CalculateFileStats(tt.files)
			require.NotNil(t, stats)

			assert.Equal(t, tt.wantTotalFiles, stats.TotalFiles)
			assert.Equal(t, tt.wantTotalLines, stats.TotalLines)
			assert.Equal(t, tt.wantTotalSize, stats.TotalSize)

			// Averages
			if tt.wantTotalFiles == 0 {
				assert.InDelta(t, 0.0, stats.AverageLines, floatDelta)
				assert.InDelta(t, 0.0, stats.AverageSize, floatDelta)
			} else {
				assert.InDelta(t, float64(tt.wantTotalLines)/float64(tt.wantTotalFiles), stats.AverageLines, floatDelta)
				assert.InDelta(t, float64(tt.wantTotalSize)/float64(tt.wantTotalFiles), stats.AverageSize, floatDelta)
			}

			// Largest/Smallest file paths
			assert.Equal(t, tt.wantLargestFile, stats.LargestFile)
			assert.Equal(t, tt.wantSmallestFile, stats.SmallestFile)

			// Languages map
			require.NotNil(t, stats.Languages)
			assert.Equal(t, tt.wantLanguages, stats.Languages)
		})
	}
}
