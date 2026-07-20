"use client";

import {
  Button,
  DrawerBody,
  DrawerHeader,
  DrawerHeaderTitle,
  OverlayDrawer,
  Text
} from "@fluentui/react-components";
import { DismissRegular } from "@fluentui/react-icons";

export function DetailDrawer({
  open,
  onOpenChange,
  title,
  payload
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  payload: unknown;
}) {
  return (
    <OverlayDrawer position="end" open={open} onOpenChange={(_, data) => onOpenChange(data.open)}>
      <DrawerHeader>
        <DrawerHeaderTitle
          action={
            <Button appearance="subtle" icon={<DismissRegular />} onClick={() => onOpenChange(false)} aria-label="Close detail drawer" />
          }
        >
          {title}
        </DrawerHeaderTitle>
      </DrawerHeader>
      <DrawerBody>
        <Text as="pre" className="json-block">
          {JSON.stringify(payload, null, 2)}
        </Text>
      </DrawerBody>
    </OverlayDrawer>
  );
}
