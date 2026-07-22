package main

import (
	"bytes"
	"fmt"
	"image"
	"image/color"
	"os"
	"path/filepath"
	"strings"

	"github.com/notnil/chess"
	"github.com/srwiley/oksvg"
	"github.com/srwiley/rasterx"
)

func drawPiece(img *image.RGBA, cx, cy, size int, pt chess.PieceType, isWhite bool, c color.RGBA, style, svgDir string) {
	if style == "svg" && svgDir != "" {
		drawSvgPiece(img, cx, cy, size, pt, isWhite, c, svgDir)
	}
}

func drawCaptured(img *image.RGBA, startX, startY, maxWidth int, pieces []chess.PieceType, isWhite bool, c color.RGBA, style, svgDir string) {
	if len(pieces) == 0 {
		return
	}

	size := 30
	spacing := 15

	cx := startX + size/2
	cy := startY + size/2

	for _, pt := range pieces {
		drawPiece(img, cx, cy, size, pt, isWhite, c, style, svgDir)
		cx += size + spacing
		if cx+size/2 > startX+maxWidth {
			cx = startX + size/2
			cy += size + spacing
		}
	}
}

func drawSvgPiece(img *image.RGBA, cx, cy, size int, pt chess.PieceType, isWhite bool, c color.RGBA, svgDir string) {
	prefix := "b"
	cTag := "d"
	if isWhite {
		prefix = "w"
		cTag = "l"
	}

	pTag := ""
	switch pt {
	case chess.King:
		pTag = "k"
	case chess.Queen:
		pTag = "q"
	case chess.Rook:
		pTag = "r"
	case chess.Bishop:
		pTag = "b"
	case chess.Knight:
		pTag = "n"
	case chess.Pawn:
		pTag = "p"
	}

	filename := fmt.Sprintf("Chess_%s%st45.svg", pTag, cTag)
	path := filepath.Join(svgDir, filename)

	if _, err := os.Stat(path); os.IsNotExist(err) {
		filename = fmt.Sprintf("%s%s.svg", prefix, strings.ToUpper(pTag))
		path = filepath.Join(svgDir, filename)
	}

	raw, err := os.ReadFile(path)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Warning: could not read SVG %s: %v\n", path, err)
		return
	}

	hexColor := fmt.Sprintf("#%02x%02x%02x", c.R, c.G, c.B)
	svgStr := string(raw)

	if isWhite {
		svgStr = strings.ReplaceAll(svgStr, "#ffffff", hexColor)
		svgStr = strings.ReplaceAll(svgStr, "#ffffcc", hexColor)
		svgStr = strings.ReplaceAll(svgStr, "#fff\"", hexColor+"\"")
	} else {
		svgStr = strings.ReplaceAll(svgStr, "#000000", hexColor)
		svgStr = strings.ReplaceAll(svgStr, "#000\"", hexColor+"\"")
	}

	icon, err := oksvg.ReadIconStream(bytes.NewReader([]byte(svgStr)))
	if err != nil {
		fmt.Fprintf(os.Stderr, "Warning: failed to parse SVG %s: %v\n", filename, err)
		return
	}

	w, h := float64(size), float64(size)
	icon.SetTarget(float64(cx)-w/2, float64(cy)-h/2, w, h)

	// Use the destination canvas dimensions to avoid buffer out-of-bounds panics
	bounds := img.Bounds()
	scanner := rasterx.NewScannerGV(bounds.Dx(), bounds.Dy(), img, bounds)
	raster := rasterx.NewDasher(bounds.Dx(), bounds.Dy(), scanner)
	icon.Draw(raster, 1.0)
}
