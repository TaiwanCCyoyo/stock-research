import {
    PANEL_ANIMATED_CARDS,
    PANEL_ENTER_MS,
    PANEL_ENTER_STAGGER,
    PANEL_LEAVE_MS,
    PANEL_LEAVE_STAGGER,
    type PanelPhase,
} from "./panelPolicy.ts";

const ID = "fh-panel-scrub";
/** Card lists in the side panel: the ranking and each strategy's holdings. */
const LISTS = ".fh-ranking-list, .fh-comp-holdings ul";
const CARDS = ":scope > .fh-rank-row, :scope > li";

/** Slide the cards out to the right, or in from below. Only transform and
 *  opacity animate; cards past the cap vanish or appear at once. */
export function playPanelPhase(root: HTMLElement, phase: PanelPhase): void {
    for (const animation of root.getAnimations({ subtree: true }))
        if (animation.id === ID) animation.cancel();
    if (phase !== "leaving" && phase !== "entering") return;
    for (const list of root.querySelectorAll<HTMLElement>(LISTS)) {
        list.querySelectorAll<HTMLElement>(CARDS).forEach((card, i) => {
            const animated = i < PANEL_ANIMATED_CARDS;
            const animation =
                phase === "leaving"
                    ? card.animate(
                          animated
                              ? [
                                    { opacity: 1, transform: "translateX(0)" },
                                    {
                                        opacity: 0,
                                        transform: "translateX(32px)",
                                    },
                                ]
                              : [{ opacity: 0 }, { opacity: 0 }],
                          {
                              duration: animated ? PANEL_LEAVE_MS : 1,
                              delay: animated ? i * PANEL_LEAVE_STAGGER : 0,
                              easing: "ease-in",
                              fill: "forwards",
                          },
                      )
                    : animated
                      ? card.animate(
                            [
                                {
                                    opacity: 0,
                                    transform: "translateY(14px)",
                                },
                                { opacity: 1, transform: "translateY(0)" },
                            ],
                            {
                                duration: PANEL_ENTER_MS,
                                delay: i * PANEL_ENTER_STAGGER,
                                easing: "ease-out",
                                fill: "backwards",
                            },
                        )
                      : null;
            if (animation) animation.id = ID;
        });
    }
}
