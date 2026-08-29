package com.windowssdwan.multilink.networking

import com.windowssdwan.multilink.model.LinkId
import com.windowssdwan.multilink.model.NetworkLinkSnapshot

/** Events that can update the set of currently-known links. */
sealed interface NetworkLinkEvent {
    /** A link appeared or one of its properties changed. */
    data class Updated(val snapshot: NetworkLinkSnapshot) : NetworkLinkEvent

    /** A link disappeared (`onLost`). */
    data class Removed(val linkId: LinkId) : NetworkLinkEvent
}

/**
 * Pure reducer from `(current links, one event) -> next links`.
 *
 * Deliberately isolated from `ConnectivityManager.NetworkCallback` so the
 * "a link disappears, then a new/same link reappears" behavior can be unit
 * tested on the plain JVM without a device, emulator, or Robolectric.
 */
object NetworkLinkReducer {
    fun reduce(
        current: Map<LinkId, NetworkLinkSnapshot>,
        event: NetworkLinkEvent
    ): Map<LinkId, NetworkLinkSnapshot> = when (event) {
        is NetworkLinkEvent.Updated -> current + (event.snapshot.linkId to event.snapshot)
        is NetworkLinkEvent.Removed -> current - event.linkId
    }
}
