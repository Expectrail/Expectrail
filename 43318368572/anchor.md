# SAM asked with a point at the engine's player position

Model sam-3.1. Calls 11, counted $0.0275 at the list price of an image (what a point request is billed at is not on the price page).

| Run | Asked | Answered | Holds the point | Confidence min / median / max | Width (game px) | Height (game px) | Below origin (game px) | Share of frame, largest |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| clean-traversal | 11 of 11 | 11 | 11 | 0.66 / 0.85 / 0.92 | 48.5 / 49 / 67 | 62.5 / 96.5 / 140.5 | 34 / 69 / 112 | 2.5% |

## clean-traversal

| Frame | Player (game) | Point (frame) | Box (frame) | Size (game px) | Above / below origin | Confidence | Holds the point | Note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 15 | 121.28, 616.79 | 805, 713 | 743, 660, 850, 786 | 53.5 x 63 | 26.5 / 36.5 | 0.851562 | yes |  |
| 16 | 126.28, 605.44 | 805, 690 | 745, 638, 842, 776 | 48.5 x 69 | 26 / 43 | 0.660156 | yes |  |
| 17 | 131.28, 594.66 | 805, 669 | 746, 615, 844, 778 | 49 x 81.5 | 27 / 54.5 | 0.835938 | yes |  |
| 18 | 136.28, 584.48 | 805, 648 | 746, 594, 843, 775 | 48.5 x 90.5 | 27 / 63.5 | 0.773438 | yes |  |
| 19 | 141.28, 574.87 | 805, 629 | 745, 574, 843, 767 | 49 x 96.5 | 27.5 / 69 | 0.828125 | yes |  |
| 20 | 146.28, 565.85 | 805, 611 | 746, 558, 843, 773 | 48.5 x 107.5 | 26.5 / 81 | 0.863281 | yes |  |
| 21 | 151.28, 557.41 | 805, 594 | 741, 539, 843, 773 | 51 x 117 | 27.5 / 89.5 | 0.875 | yes |  |
| 22 | 156.28, 549.56 | 805, 579 | 726, 523, 843, 777 | 58.5 x 127 | 28 / 99 | 0.828125 | yes |  |
| 23 | 161.28, 542.29 | 805, 564 | 718, 507, 843, 777 | 62.5 x 135 | 28.5 / 106.5 | 0.882812 | yes |  |
| 24 | 166.28, 535.6 | 805, 551 | 710, 494, 844, 775 | 67 x 140.5 | 28.5 / 112 | 0.917969 | yes |  |
| 25 | 171.28, 529.5 | 805, 538 | 745, 481, 843, 606 | 49 x 62.5 | 28.5 / 34 | 0.894531 | yes |  |

A box is in frame pixels, left, top, right, bottom, with right and bottom one past the last pixel. Game pixels are frame pixels divided by the camera's scale. "Below origin" is how far the box reaches under the engine's player position: on a clean run it is the distance from the origin to the feet as drawn.
