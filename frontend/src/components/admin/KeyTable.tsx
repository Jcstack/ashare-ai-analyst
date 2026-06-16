import { useState } from "react"
import { Trash2, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import type { ApiKeyInfo } from "@/types/admin"

interface KeyTableProps {
  keys: ApiKeyInfo[]
  onAdd: (provider: string, key: string, label: string) => void
  onRemove: (provider: string, label: string) => void
}

export function KeyTable({ keys, onAdd, onRemove }: KeyTableProps) {
  const [open, setOpen] = useState(false)
  const [provider, setProvider] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [label, setLabel] = useState("")

  const handleSubmit = () => {
    if (provider && apiKey && label) {
      onAdd(provider, apiKey, label)
      setProvider("")
      setApiKey("")
      setLabel("")
      setOpen(false)
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between py-3">
        <CardTitle className="text-sm">API 密钥</CardTitle>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm" variant="outline">
              <Plus className="h-4 w-4 mr-1" />
              添加密钥
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>添加 API 密钥</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div>
                <Label>提供商</Label>
                <Input value={provider} onChange={(e) => setProvider(e.target.value)} placeholder="anthropic" />
              </div>
              <div>
                <Label>密钥</Label>
                <Input value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-..." type="password" />
              </div>
              <div>
                <Label>标签</Label>
                <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="production-key" />
              </div>
              <Button onClick={handleSubmit} className="w-full">添加</Button>
            </div>
          </DialogContent>
        </Dialog>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>提供商</TableHead>
              <TableHead>标签</TableHead>
              <TableHead>密钥</TableHead>
              <TableHead>状态</TableHead>
              <TableHead className="w-16"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {keys.map((k) => (
              <TableRow key={`${k.provider}-${k.label}`}>
                <TableCell>
                  <Badge variant="secondary">{k.provider}</Badge>
                </TableCell>
                <TableCell className="font-medium">{k.label}</TableCell>
                <TableCell className="font-mono text-sm text-muted-foreground">
                  {k.masked_key ?? "***"}
                </TableCell>
                <TableCell>
                  <Badge variant={k.status === "active" ? "default" : "secondary"}>
                    {k.status ?? "active"}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => onRemove(k.provider, k.label)}
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {keys.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                  暂无密钥
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
