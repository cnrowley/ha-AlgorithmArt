package main

import (
	"image"
	"image/color"
	"os"

	"golang.org/x/image/font"
	"golang.org/x/image/font/opentype"
	"golang.org/x/image/math/fixed"
)

var (
	parsedFont *opentype.Font
	faceCache  = make(map[int]font.Face)
)

func initFont(path string) {
	if path == "" {
		return // Will skip drawing text if no font is provided
	}

	fontBytes, err := os.ReadFile(path)
	if err != nil {
		panic(err)
	}

	f, err := opentype.Parse(fontBytes)
	if err != nil {
		panic(err)
	}
	parsedFont = f
}

func getFace(size int) font.Face {
	if face, ok := faceCache[size]; ok {
		return face
	}

	face, err := opentype.NewFace(parsedFont, &opentype.FaceOptions{
		Size:    float64(size),
		DPI:     72,
		Hinting: font.HintingNone,
	})
	if err != nil {
		panic(err)
	}

	faceCache[size] = face
	return face
}

func drawText(img *image.RGBA, x, y int, text string, c color.RGBA, size int, align string) {
	if parsedFont == nil {
		return
	}

	face := getFace(size)
	bound, _ := font.BoundString(face, text)
	width := (bound.Max.X - bound.Min.X).Ceil()
	height := (bound.Max.Y - bound.Min.Y).Ceil()

	startX := x
	if align == "center" {
		startX = x - width/2
	} else if align == "right" {
		startX = x - width
	}

	// Adjust Y to sit on the baseline correctly
	startY := y + height/2 

	d := &font.Drawer{
		Dst:  img,
		Src:  image.NewUniform(c),
		Face: face,
		Dot:  fixed.Point26_6{X: fixed.I(startX), Y: fixed.I(startY)},
	}
	d.DrawString(text)
}