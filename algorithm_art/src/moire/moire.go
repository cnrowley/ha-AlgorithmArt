package main

import (
    "flag"
    "fmt"
    "image"
    "image/color"
    "math"
    "math/rand"
    "os"
    "time"

    "golang.org/x/image/bmp"
)

type Pattern string

const (
    Lines        Pattern = "lines"
    Square       Pattern = "square"
    HexDots      Pattern = "hexdots"
    Honeycomb    Pattern = "honeycomb"
    Triangular   Pattern = "triangular"
    Kagome       Pattern = "kagome"
    Circles      Pattern = "circles"
    Spokes       Pattern = "spokes"
    Checkerboard Pattern = "checkerboard"
)

type Config struct {
    Width    int
    Height   int
    Pattern  Pattern
    Rotation float64
    TX       float64
    TY       float64
    Output   string
}

func main() {

    rand.Seed(time.Now().UnixNano())

    cfg := parseFlags()

    img := image.NewRGBA(
        image.Rect(0, 0, cfg.Width, cfg.Height),
    )

    fillWhite(img)

    switch cfg.Pattern {

    case Lines:
        drawLines(img, cfg)

    case Square:
        drawSquare(img, cfg)

    case HexDots:
        drawHexDots(img, cfg)

    case Honeycomb:
        drawHoneycomb(img, cfg)

    case Triangular:
        drawTriangular(img, cfg)

    case Kagome:
        drawKagome(img, cfg)

    case Circles:
        drawCircles(img, cfg)

    case Spokes:
        drawSpokes(img, cfg)

    case Checkerboard:
        drawCheckerboard(img, cfg)

    default:
        drawHexDots(img, cfg)
    }

    f, err := os.Create(cfg.Output)
    if err != nil {
        panic(err)
    }
    defer f.Close()

    if err := bmp.Encode(f, img); err != nil {
        panic(err)
    }

    fmt.Println("Wrote:", cfg.Output)
}

func parseFlags() Config {

    cfg := Config{}

    flag.IntVar(&cfg.Width,
        "width",
        800,
        "image width")

    flag.IntVar(&cfg.Height,
        "height",
        480,
        "image height")

    pattern := flag.String(
        "pattern",
        "hexdots",
        "pattern")

    flag.Float64Var(
        &cfg.Rotation,
        "rotation",
        2.0,
        "rotation degrees")

    flag.Float64Var(
        &cfg.TX,
        "tx",
        10,
        "translation x")

    flag.Float64Var(
        &cfg.TY,
        "ty",
        10,
        "translation y")

    flag.StringVar(
        &cfg.Output,
        "output",
        "current.bmp",
        "output bmp")

    flag.Parse()

    cfg.Pattern = Pattern(*pattern)

    return cfg
}

func fillWhite(img *image.RGBA) {

    white := color.RGBA{255, 255, 255, 255}

    b := img.Bounds()

    for y := b.Min.Y; y < b.Max.Y; y++ {
        for x := b.Min.X; x < b.Max.X; x++ {
            img.SetRGBA(x, y, white)
        }
    }
}

func transform(
    x,
    y,
    rotDeg,
    tx,
    ty float64,
) (float64, float64) {

    t := rotDeg * math.Pi / 180

    c := math.Cos(t)
    s := math.Sin(t)

    xx := c*x - s*y + tx
    yy := s*x + c*y + ty

    return xx, yy
}

func plot(
    img *image.RGBA,
    x,
    y int,
) {

    if x < 0 || y < 0 ||
        x >= img.Bounds().Dx() ||
        y >= img.Bounds().Dy() {
        return
    }

    img.SetRGBA(
        x,
        y,
        color.RGBA{0, 0, 0, 255},
    )
}

func drawLine(
    img *image.RGBA,
    x0,
    y0,
    x1,
    y1 int,
) {

    dx := int(math.Abs(float64(x1 - x0)))
    dy := -int(math.Abs(float64(y1 - y0)))

    sx := -1
    if x0 < x1 {
        sx = 1
    }

    sy := -1
    if y0 < y1 {
        sy = 1
    }

    err := dx + dy

    for {

        plot(img, x0, y0)

        if x0 == x1 && y0 == y1 {
            break
        }

        e2 := 2 * err

        if e2 >= dy {
            err += dy
            x0 += sx
        }

        if e2 <= dx {
            err += dx
            y0 += sy
        }
    }
}

func drawSegmentPair(
    img *image.RGBA,
    cfg Config,
    x1,
    y1,
    x2,
    y2 float64,
) {

    w2 := float64(cfg.Width) / 2
    h2 := float64(cfg.Height) / 2

    drawLine(
        img,
        int(x1+w2),
        int(y1+h2),
        int(x2+w2),
        int(y2+h2),
    )

    tx1, ty1 := transform(
        x1, y1,
        cfg.Rotation,
        cfg.TX,
        cfg.TY)

    tx2, ty2 := transform(
        x2, y2,
        cfg.Rotation,
        cfg.TX,
        cfg.TY)

    drawLine(
        img,
        int(tx1+w2),
        int(ty1+h2),
        int(tx2+w2),
        int(ty2+h2),
    )
}

func drawLines(img *image.RGBA, cfg Config) {

    spacing := 20

    for x := -cfg.Width; x < 2*cfg.Width; x += spacing {

        drawSegmentPair(
            img, cfg,
            float64(x), -float64(cfg.Height),
            float64(x), 2*float64(cfg.Height),
        )
    }
}

func drawSquare(img *image.RGBA, cfg Config) {

    spacing := 30

    for x := -cfg.Width; x < 2*cfg.Width; x += spacing {

        drawSegmentPair(
            img, cfg,
            float64(x), -float64(cfg.Height),
            float64(x), 2*float64(cfg.Height))
    }

    for y := -cfg.Height; y < 2*cfg.Height; y += spacing {

        drawSegmentPair(
            img, cfg,
            -float64(cfg.Width), float64(y),
            2*float64(cfg.Width), float64(y))
    }
}

func drawHexDots(img *image.RGBA, cfg Config) {

    spacing := 25.0

    dy := math.Sqrt(3) * spacing / 2

    row := 0

    for y := -float64(cfg.Height); y < 2*float64(cfg.Height); y += dy {

        shift := 0.0
        if row%2 == 1 {
            shift = spacing / 2
        }

        for x := -float64(cfg.Width); x < 2*float64(cfg.Width); x += spacing {

            plot(
                img,
                int(x+shift)+cfg.Width/2,
                int(y)+cfg.Height/2)

            xx, yy := transform(
                x+shift,
                y,
                cfg.Rotation,
                cfg.TX,
                cfg.TY)

            plot(
                img,
                int(xx)+cfg.Width/2,
                int(yy)+cfg.Height/2)
        }

        row++
    }
}

func drawHoneycomb(img *image.RGBA, cfg Config) {

    numCellsX := 30.0

    bond := float64(cfg.Width) /
        (numCellsX * math.Sqrt(3))

    sqrt3 := math.Sqrt(3)

    a1x := sqrt3 * bond
    a1y := 0.0

    a2x := sqrt3 * bond / 2
    a2y := 1.5 * bond

    dirs := [][2]float64{
        {0, bond},
        {-sqrt3 * bond / 2, -bond / 2},
        {sqrt3 * bond / 2, -bond / 2},
    }

    N := 80

    for i := -N; i < N; i++ {

        for j := -N; j < N; j++ {

            ax := float64(i)*a1x +
                float64(j)*a2x

            ay := float64(i)*a1y +
                float64(j)*a2y

            for _, d := range dirs {

                drawSegmentPair(
                    img,
                    cfg,
                    ax,
                    ay,
                    ax+d[0],
                    ay+d[1],
                )
            }
        }
    }
}

func drawTriangular(img *image.RGBA, cfg Config) {

    s := 25.0
    h := math.Sqrt(3) * s / 2

    for row := -30; row < 60; row++ {

        shift := 0.0

        if row%2 != 0 {
            shift = s / 2
        }

        for col := -40; col < 80; col++ {

            x := float64(col)*s + shift
            y := float64(row) * h

            drawSegmentPair(img, cfg, x, y, x+s, y)
            drawSegmentPair(img, cfg, x, y, x+s/2, y+h)
            drawSegmentPair(img, cfg, x+s, y, x+s/2, y+h)
        }
    }
}

func drawKagome(img *image.RGBA, cfg Config) {

    s := 30.0
    h := math.Sqrt(3) * s / 2

    for row := -30; row < 60; row++ {

        shift := 0.0

        if row%2 != 0 {
            shift = s / 2
        }

        for col := -40; col < 80; col++ {

            x := float64(col)*s + shift
            y := float64(row) * h

            drawSegmentPair(
                img, cfg,
                x, y,
                x+s/2, y)

            drawSegmentPair(
                img, cfg,
                x+s/2, y,
                x+s/4, y+h/2)

            drawSegmentPair(
                img, cfg,
                x+s/4, y+h/2,
                x, y)
        }
    }
}

func drawCircles(img *image.RGBA, cfg Config) {

    cx := float64(cfg.Width) / 2
    cy := float64(cfg.Height) / 2

    for r := 20.0; r < 800; r += 20 {

        for th := 0.0; th < 2*math.Pi; th += 0.01 {

            x := cx + r*math.Cos(th)
            y := cy + r*math.Sin(th)

            plot(img, int(x), int(y))

            xx, yy := transform(
                x-cx,
                y-cy,
                cfg.Rotation,
                cfg.TX,
                cfg.TY)

            plot(
                img,
                int(xx+cx),
                int(yy+cy))
        }
    }
}

func drawSpokes(img *image.RGBA, cfg Config) {

    R := 800.0

    for k := 0; k < 60; k++ {

        t := 2 * math.Pi * float64(k) / 60

        drawSegmentPair(
            img,
            cfg,
            0,
            0,
            R*math.Cos(t),
            R*math.Sin(t),
        )
    }
}

func drawCheckerboard(img *image.RGBA, cfg Config) {

    cell := 25

    for y := -cfg.Height; y < cfg.Height; y += cell {

        for x := -cfg.Width; x < cfg.Width; x += cell {

            if ((x/cell)+(y/cell))%2 != 0 {
                continue
            }

            for yy := y; yy < y+cell; yy++ {

                for xx := x; xx < x+cell; xx++ {

                    plot(
                        img,
                        xx+cfg.Width/2,
                        yy+cfg.Height/2)

                    rx, ry := transform(
                        float64(xx),
                        float64(yy),
                        cfg.Rotation,
                        cfg.TX,
                        cfg.TY)

                    plot(
                        img,
                        int(rx)+cfg.Width/2,
                        int(ry)+cfg.Height/2)
                }
            }
        }
    }
}

