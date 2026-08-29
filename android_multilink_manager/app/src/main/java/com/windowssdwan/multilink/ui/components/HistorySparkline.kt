package com.windowssdwan.multilink.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.unit.dp

/**
 * A tiny in-memory history sparkline (no chart library dependency), drawn
 * with a plain Compose [Canvas]. Shows the last N score values (0-100) for
 * one link, purely as a visual trend indicator.
 */
@Composable
fun HistorySparkline(
    values: List<Int>,
    lineColor: Color,
    modifier: Modifier = Modifier
) {
    Box(modifier = modifier.fillMaxWidth().height(36.dp), contentAlignment = Alignment.Center) {
        if (values.size < 2) {
            Text(
                text = "Not enough history yet",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            return@Box
        }

        Canvas(modifier = Modifier.fillMaxWidth().height(36.dp)) {
            val stepX = size.width / (values.size - 1).coerceAtLeast(1)
            fun yFor(score: Int): Float {
                val clamped = score.coerceIn(0, 100)
                // Higher score should draw higher on the canvas (smaller y).
                return size.height * (1f - clamped / 100f)
            }

            for (i in 0 until values.size - 1) {
                drawLine(
                    color = lineColor,
                    start = Offset(i * stepX, yFor(values[i])),
                    end = Offset((i + 1) * stepX, yFor(values[i + 1])),
                    strokeWidth = 4f,
                    cap = StrokeCap.Round
                )
            }
        }
    }
}
