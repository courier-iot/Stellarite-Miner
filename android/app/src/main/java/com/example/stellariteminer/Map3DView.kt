package com.example.stellariteminer

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Typeface
import android.util.AttributeSet
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin

/** A dot in the 3D map. */
class MapPoint(val x: Double, val y: Double, val z: Double, val color: Int, val radiusDp: Float,
               val label: String? = null, val alwaysLabel: Boolean = false, val glow: Boolean = false,
               val info: String? = null, val key: String? = null)

/** A polyline in the 3D map. */
class MapLine(val pts: List<DoubleArray>, val color: Int, val widthDp: Float, val alpha: Int = 255,
              val dashed: Boolean = false)

/**
 * Lightweight 3D viewer drawn with Canvas: perspective projection, drag to
 * rotate, pinch to zoom, double-tap to reset, slow auto-rotation when idle.
 * No OpenGL needed; a few thousand points and lines draw smoothly.
 */
class Map3DView @JvmOverloads constructor(ctx: Context, attrs: AttributeSet? = null) : View(ctx, attrs) {
    private val d = resources.displayMetrics.density
    private var points: List<MapPoint> = emptyList()
    private var lines: List<MapLine> = emptyList()
    private var rings: List<Double> = emptyList()
    private var ringUnit = ""
    private var worldRadius = 1.0

    private var yaw = 0.6
    private var pitch = 1.05            // radians from looking straight down
    private var zoom = 1.0
    private var lastTouch = 0L

    /** Called with the tapped point (or null when tapping empty space). */
    var onPick: ((MapPoint?) -> Unit)? = null
    /** Key of the selected point, drawn with a ring; survives scene rebuilds. */
    var selectedKey: String? = null
    private var lastProjected: List<Pair<MapPoint, FloatArray>> = emptyList()

    private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeCap = Paint.Cap.ROUND }
    private val dotPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = 10 * d; color = Theme.TEXT; typeface = Typeface.MONOSPACE
    }
    private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; color = Theme.CRIMSON_DIM; strokeWidth = 1 * d
    }
    private val ringLabel = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = 9 * d; color = Theme.MUTED; typeface = Typeface.MONOSPACE
    }

    /** Replace the scene. [rings] are reference circles (in world units) drawn in the x-y plane. */
    fun setScene(points: List<MapPoint>, lines: List<MapLine>, rings: List<Double>, ringUnit: String) {
        this.points = points
        this.lines = lines
        this.rings = rings
        this.ringUnit = ringUnit
        var r = 1e-9
        points.forEach { r = max(r, Math.sqrt(it.x * it.x + it.y * it.y + it.z * it.z)) }
        rings.forEach { r = max(r, it) }
        worldRadius = r
        invalidate()
    }

    fun setTypeface(tf: Typeface?) {
        if (tf != null) { labelPaint.typeface = tf; ringLabel.typeface = tf }
    }

    fun resetView() { yaw = 0.6; pitch = 1.05; zoom = 1.0; invalidate() }

    // ---- projection ---------------------------------------------------

    private val out = FloatArray(3)

    /**
     * World -> screen. out = (screen x, screen y, depth toward the viewer).
     * Rotate by yaw around z, then tilt by pitch (0 = top-down, pi/2 = edge-on), then perspective.
     */
    private fun project(x: Double, y: Double, z: Double) {
        val cy = cos(yaw); val sy = sin(yaw)
        val x1 = x * cy - y * sy
        val y1 = x * sy + y * cy
        val cp = cos(pitch); val sp = sin(pitch)
        val up = y1 * cp + z * sp                 // screen-up component
        val toward = z * cp - y1 * sp             // toward the viewer
        val camDist = worldRadius * 3.2
        val persp = camDist / max(camDist - toward, camDist * 0.05)
        val scale = min(width, height) * 0.46 / worldRadius * zoom
        out[0] = (width / 2.0 + x1 * scale * persp).toFloat()
        out[1] = (height / 2.0 - up * scale * persp).toFloat()
        out[2] = toward.toFloat()
    }

    override fun onDraw(canvas: Canvas) {
        if (points.isEmpty() && lines.isEmpty()) return

        // reference rings
        for (r in rings) {
            val path = Path()
            for (k in 0..72) {
                val a = 2 * Math.PI * k / 72
                project(r * cos(a), r * sin(a), 0.0)
                if (k == 0) path.moveTo(out[0], out[1]) else path.lineTo(out[0], out[1])
            }
            canvas.drawPath(path, ringPaint)
            project(r * cos(-0.35), r * sin(-0.35), 0.0)
            canvas.drawText(formatRing(r), out[0] + 4 * d, out[1], ringLabel)
        }

        // lines
        for (l in lines) {
            if (l.pts.size < 2) continue
            val path = Path()
            l.pts.forEachIndexed { i, p ->
                project(p[0], p[1], p[2])
                if (i == 0) path.moveTo(out[0], out[1]) else path.lineTo(out[0], out[1])
            }
            linePaint.color = l.color
            linePaint.alpha = l.alpha
            linePaint.strokeWidth = l.widthDp * d
            linePaint.pathEffect = if (l.dashed) android.graphics.DashPathEffect(floatArrayOf(4 * d, 5 * d), 0f) else null
            canvas.drawPath(path, linePaint)
        }

        // points, far to near
        val proj = points.map { p -> project(p.x, p.y, p.z); Triple(p, floatArrayOf(out[0], out[1]), out[2]) }
            .sortedBy { it.third }
        lastProjected = proj.map { it.first to it.second }
        for ((p, xy, _) in proj) {
            if (p.key != null && p.key == selectedKey) {
                linePaint.color = Theme.AMBER; linePaint.alpha = 255; linePaint.strokeWidth = 1.5f * d; linePaint.pathEffect = null
                canvas.drawCircle(xy[0], xy[1], p.radiusDp * d + 7 * d, linePaint)
            }
            if (p.glow) {
                dotPaint.color = p.color; dotPaint.alpha = 70
                canvas.drawCircle(xy[0], xy[1], p.radiusDp * d * 2.6f, dotPaint)
            }
            dotPaint.color = p.color; dotPaint.alpha = 255
            canvas.drawCircle(xy[0], xy[1], p.radiusDp * d, dotPaint)
        }

        // labels: important ones first, skipping any that would overlap one already drawn
        val placed = ArrayList<android.graphics.RectF>()
        val candidates = proj.filter { it.first.label != null && (it.first.alwaysLabel || zoom > 2.2) }
            .sortedWith(compareByDescending<Triple<MapPoint, FloatArray, Float>> { it.first.alwaysLabel }
                .thenByDescending { it.first.glow }.thenByDescending { it.third })
        for ((p, xy, _) in candidates) {
            val text = p.label!!
            val x = xy[0] + p.radiusDp * d + 3 * d
            val y = xy[1] - 3 * d
            val r = android.graphics.RectF(x, y - labelPaint.textSize, x + labelPaint.measureText(text), y + 2 * d)
            if (placed.any { android.graphics.RectF.intersects(it, r) }) continue
            placed += r
            canvas.drawText(text, x, y, labelPaint)
        }

        // slow auto-rotation when idle
        if (System.currentTimeMillis() - lastTouch > 4000 && selectedKey == null) {
            yaw += 0.0025
            postInvalidateOnAnimation()
        }
    }

    private fun formatRing(r: Double): String =
        if (r >= 10 || r == Math.floor(r)) "${r.toInt()} $ringUnit" else "$r $ringUnit"

    // ---- touch --------------------------------------------------------

    private var lastX = 0f
    private var lastY = 0f

    private val scaler = ScaleGestureDetector(ctx, object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
        override fun onScale(det: ScaleGestureDetector): Boolean {
            zoom = (zoom * det.scaleFactor).coerceIn(0.4, 12.0)
            invalidate()
            return true
        }
    })

    private val gestures = GestureDetector(ctx, object : GestureDetector.SimpleOnGestureListener() {
        override fun onDoubleTap(e: MotionEvent): Boolean { resetView(); return true }
        override fun onSingleTapConfirmed(e: MotionEvent): Boolean {
            val hit = lastProjected.filter { it.first.info != null }
                .minByOrNull { (_, xy) -> (xy[0] - e.x) * (xy[0] - e.x) + (xy[1] - e.y) * (xy[1] - e.y) }
            val near = hit != null && Math.hypot((hit.second[0] - e.x).toDouble(), (hit.second[1] - e.y).toDouble()) < 30 * d
            selectedKey = if (near) hit!!.first.key else null
            onPick?.invoke(if (near) hit!!.first else null)
            invalidate()
            return true
        }
    })

    override fun onTouchEvent(e: MotionEvent): Boolean {
        lastTouch = System.currentTimeMillis()
        scaler.onTouchEvent(e)
        gestures.onTouchEvent(e)
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> { lastX = e.x; lastY = e.y; parent?.requestDisallowInterceptTouchEvent(true) }
            MotionEvent.ACTION_MOVE -> if (!scaler.isInProgress && e.pointerCount == 1) {
                yaw += (e.x - lastX) / (width.coerceAtLeast(1)) * 3.5
                pitch = (pitch - (e.y - lastY) / (height.coerceAtLeast(1)) * 3.0).coerceIn(0.0, Math.PI / 2)
                lastX = e.x; lastY = e.y
                invalidate()
            }
            MotionEvent.ACTION_POINTER_UP -> { lastX = e.x; lastY = e.y }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                parent?.requestDisallowInterceptTouchEvent(false)
                invalidate()
            }
        }
        return true
    }
}
