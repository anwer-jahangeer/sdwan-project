package com.windowssdwan.multilink.policy

import com.windowssdwan.multilink.model.LinkId
import com.windowssdwan.multilink.model.TransportKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SelectionPolicyTest {

    private val wifi = LinkId(1L)
    private val cellular = LinkId(2L)

    @Test
    fun `no candidates selects nothing`() {
        val policy = SelectionPolicy()
        val decision = policy.decide(now = 0L, previous = null, candidates = emptyList())
        assertNull(decision.selectedLinkId)
    }

    @Test
    fun `no previous selection immediately picks the best candidate`() {
        val policy = SelectionPolicy()
        val decision = policy.decide(
            now = 0L,
            previous = null,
            candidates = listOf(
                SelectionCandidate(wifi, TransportKind.WIFI, 60),
                SelectionCandidate(cellular, TransportKind.CELLULAR, 90)
            )
        )
        assertEquals(cellular, decision.selectedLinkId)
    }

    @Test
    fun `equal-scoring current selection is kept without switching`() {
        val policy = SelectionPolicy()
        val first = policy.decide(0L, null, listOf(SelectionCandidate(wifi, TransportKind.WIFI, 80)))
        val second = policy.decide(
            1_000L,
            first,
            listOf(
                SelectionCandidate(wifi, TransportKind.WIFI, 80),
                SelectionCandidate(cellular, TransportKind.CELLULAR, 80)
            )
        )
        assertEquals(wifi, second.selectedLinkId)
    }

    @Test
    fun `within hold-down window a clearly better challenger is not switched to yet`() {
        val config = SelectionPolicyConfig(holdDownMs = 15_000L, switchMarginPoints = 5)
        val policy = SelectionPolicy(config)
        val first = policy.decide(0L, null, listOf(SelectionCandidate(wifi, TransportKind.WIFI, 50)))

        // Cellular is now much better, but only 5 seconds have passed (< 15s hold-down).
        val second = policy.decide(
            5_000L,
            first,
            listOf(
                SelectionCandidate(wifi, TransportKind.WIFI, 50),
                SelectionCandidate(cellular, TransportKind.CELLULAR, 95)
            )
        )
        assertEquals(wifi, second.selectedLinkId)
    }

    @Test
    fun `after hold-down expires a challenger beating the margin triggers a switch`() {
        val config = SelectionPolicyConfig(holdDownMs = 10_000L, switchMarginPoints = 8)
        val policy = SelectionPolicy(config)
        val first = policy.decide(0L, null, listOf(SelectionCandidate(wifi, TransportKind.WIFI, 50)))

        val second = policy.decide(
            20_000L, // past the 10s hold-down
            first,
            listOf(
                SelectionCandidate(wifi, TransportKind.WIFI, 50),
                SelectionCandidate(cellular, TransportKind.CELLULAR, 65) // +15 margin, >= 8
            )
        )
        assertEquals(cellular, second.selectedLinkId)
    }

    @Test
    fun `after hold-down expires a challenger within the margin does not trigger a switch`() {
        val config = SelectionPolicyConfig(holdDownMs = 10_000L, switchMarginPoints = 8)
        val policy = SelectionPolicy(config)
        val first = policy.decide(0L, null, listOf(SelectionCandidate(wifi, TransportKind.WIFI, 50)))

        val second = policy.decide(
            20_000L,
            first,
            listOf(
                SelectionCandidate(wifi, TransportKind.WIFI, 50),
                SelectionCandidate(cellular, TransportKind.CELLULAR, 55) // only +5, below margin of 8
            )
        )
        assertEquals(wifi, second.selectedLinkId)
    }

    @Test
    fun `previously selected link disappearing forces an immediate reselection`() {
        val config = SelectionPolicyConfig(holdDownMs = 60_000L, switchMarginPoints = 8)
        val policy = SelectionPolicy(config)
        val first = policy.decide(0L, null, listOf(SelectionCandidate(wifi, TransportKind.WIFI, 90)))

        // Wi-Fi is gone; only cellular remains, well within what would have been the hold-down window.
        val second = policy.decide(1_000L, first, listOf(SelectionCandidate(cellular, TransportKind.CELLULAR, 40)))
        assertEquals(cellular, second.selectedLinkId)
    }
}
