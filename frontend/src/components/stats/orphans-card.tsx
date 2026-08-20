import { useState } from "react"
import { Link } from "react-router-dom"
import { FolderPlus, PencilLine, Trash2 } from "lucide-react"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  useAdoptOrphanToGroup,
  useAdoptOrphanToThesis,
  useDeleteOrphan,
  useGroups,
  useOrphans,
  useTheses,
} from "@/lib/queries"
import type { OrphanAsset } from "@/lib/types"

/** The part of a hard delete that can't be undone by re-adding the ticker,
 *  phrased for the confirm dialog. Null when there's nothing hand-written to
 *  lose, which is the common case. */
function handwrittenLoss(o: OrphanAsset): string | null {
  const parts: string[] = []
  if (o.has_note) parts.push("a thesis note")
  if (o.annotations > 0) {
    parts.push(`${o.annotations} chart annotation${o.annotations === 1 ? "" : "s"}`)
  }
  return parts.length ? parts.join(" and ") : null
}

/**
 * Orphaned asset rows (no group, thesis, or pseudo-ETF — leftovers of the
 * soft delete) with the two ways out: re-adopt into a group/thesis, or
 * hard-delete the row and its stored price history. Hidden when there are
 * none.
 *
 * Being orphaned is about containers, not content: a row here can still carry
 * a note and annotations, which the delete cascades away. Those are the only
 * unrecoverable part, so the table marks them and the confirm dialog spells
 * out the loss.
 */
export function OrphansCard() {
  const { data: orphans } = useOrphans()
  const { data: groups } = useGroups()
  const { data: theses } = useTheses()
  const adoptToGroup = useAdoptOrphanToGroup()
  const adoptToThesis = useAdoptOrphanToThesis()
  const deleteOrphan = useDeleteOrphan()
  const [pendingDelete, setPendingDelete] = useState<OrphanAsset | null>(null)

  if (!orphans || orphans.length === 0) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Orphaned Assets</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-xs text-muted-foreground">
          Removed from every group and referenced by no thesis or pseudo-ETF. Their price
          history sticks around until you re-adopt or delete them. A flagged row still has
          notes or annotations you wrote — deleting it throws those away for good.
        </p>
        <div className="max-h-64 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="py-1 font-medium">Symbol</th>
                <th className="py-1 font-medium">Name</th>
                <th className="py-1 text-right font-medium">Bars</th>
                <th className="py-1 text-right font-medium">Last bar</th>
                <th className="py-1" />
              </tr>
            </thead>
            <tbody>
              {orphans.map((o) => (
                <tr key={o.id} className="border-t border-border/50">
                  <td className="py-1.5 font-medium">
                    <span className="flex items-center gap-1">
                      <Link to={`/asset/${o.symbol}`} className="hover:text-primary hover:underline">
                        {o.symbol}
                      </Link>
                      {handwrittenLoss(o) && (
                        <span
                          title={`Has ${handwrittenLoss(o)} — deleting loses them`}
                          aria-label={`Has ${handwrittenLoss(o)}`}
                          className="flex shrink-0"
                        >
                          <PencilLine className="h-3.5 w-3.5 text-amber-500" />
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="max-w-48 truncate py-1.5 text-muted-foreground">{o.name}</td>
                  <td className="py-1.5 text-right tabular-nums">{o.price_bars}</td>
                  <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                    {o.latest_bar ?? "—"}
                  </td>
                  <td className="py-1.5">
                    <div className="flex justify-end gap-1">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" className="h-7 w-7 cursor-pointer" title="Add to group or thesis">
                            <FolderPlus className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuLabel>Add to group</DropdownMenuLabel>
                          {(groups ?? []).map((g) => (
                            <DropdownMenuItem
                              key={g.id}
                              onClick={() => adoptToGroup.mutate({ groupId: g.id, assetId: o.id })}
                            >
                              {g.name}
                            </DropdownMenuItem>
                          ))}
                          {(theses ?? []).length > 0 && (
                            <>
                              <DropdownMenuSeparator />
                              <DropdownMenuLabel>Add to thesis</DropdownMenuLabel>
                              {(theses ?? []).map((t) => (
                                <DropdownMenuItem
                                  key={t.id}
                                  onClick={() => adoptToThesis.mutate({ thesisId: t.id, assetId: o.id })}
                                >
                                  {t.name}
                                </DropdownMenuItem>
                              ))}
                            </>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 cursor-pointer text-red-500 hover:text-red-600"
                        title="Delete asset and its price history"
                        onClick={() => setPendingDelete(o)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>

      <AlertDialog open={pendingDelete !== null} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {pendingDelete?.symbol}?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently removes the asset row and its {pendingDelete?.price_bars} stored
              price bars. If you re-add the ticker later, the history is re-fetched from the configured provider.
            </AlertDialogDescription>
            {pendingDelete && handwrittenLoss(pendingDelete) && (
              <AlertDialogDescription className="text-destructive font-medium">
                It also deletes {handwrittenLoss(pendingDelete)} you wrote for {pendingDelete.symbol}.
                That can't be re-fetched — adopt it into a group or thesis instead if you want to
                keep it.
              </AlertDialogDescription>
            )}
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 text-white hover:bg-red-700"
              onClick={() => {
                if (pendingDelete) deleteOrphan.mutate(pendingDelete.id)
                setPendingDelete(null)
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
